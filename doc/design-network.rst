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
NIC slot called ``network``, a new ``Network`` configuration object
(cluster level) and logic to perform IP address pool management, i.e.
maintain a set of available and occupied IP addresses.

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

Each network will be connected to any number of node groups. During the
connection of a network to a nodegroup, we define the corresponding
connectivity mode (bridged or routed) and the host interface (br100 or
routing_table_200). This is achieved by adding a ``networks`` slot to
the NodeGroup object and using the networks' UUIDs as keys. The value
for each key is a dictionary containing the network's ``mode`` and
``link`` (netparams). Every NIC assigned to the network will eventually
inherit the network's netparams, as its nicparams.


IP pool management
++++++++++++++++++

A new helper library is introduced, wrapping around Network objects to
give IP pool management capabilities. A network's pool is defined by two
bitfields, the length of the network size each:

``reservations``
  This field holds all IP addresses reserved by Ganeti instances.

``external reservations``
  This field holds all IP addresses that are manually reserved by the
  administrator (external gateway, IPs of external servers, etc) or
  automatically by ganeti (the network/broadcast addresses,
  Cluster IPs (node addresses + cluster master)). These IPs are excluded
  from the IP pool and cannot be assigned automatically by ganeti to
  instances (via ip=pool).

The bitfields are implemented using the python-bitarray package for
space efficiency and their binary value stored base64-encoded for JSON
compatibility. This approach gives relatively compact representations
even for large IPv4 networks (e.g. /20).

Cluster IP addresses (node + master IPs) are reserved automatically
as external if the cluster's data network itself is placed under
pool management.

Helper ConfigWriter methods provide free IP address generation and
reservation, using a TemporaryReservationManager.

It should be noted that IP pool management is performed only for IPv4
networks, as they are expected to be densely populated. IPv6 networks
can use different approaches, e.g. sequential address asignment or
EUI-64 addresses.

New NIC parameter: network
++++++++++++++++++++++++++

In order to be able to use the new network facility while maintaining
compatibility with the current networking model, a new NIC parameter is
introduced, called ``network`` to reflect the fact that the given NIC
belongs to the given network and its configuration is managed by Ganeti
itself. To keep backwards compatibility, existing code is executed if
the ``network`` value is 'none' or omitted during NIC creation. If we
want our NIC to be assigned to a network, then only the ip (optional)
and the network parameters should be passed. Mode and link are inherited
from the network-nodegroup mapping configuration (netparams). This
provides the desired abstraction between the VM's network and the
node-specific underlying infrastructure.

We also introduce a new ``ip`` address value, ``constants.NIC_IP_POOL``,
that specifies that a given NIC's IP address should be obtained using
the first available IP address inside the pool of the specified network.
(reservations OR external_reservations). This value is only valid
for NICs belonging to a network. A NIC's IP address can also be
specified manually, as long as it is contained in the network the NIC
is connected to. In case this IP is externally reserved, Ganeti will produce
an error which the user can override if explicitly requested. Of course
this IP will be reserved and will not be able to be assigned to another
instance.


Hooks
+++++

Introduce new hooks concerning network operations:

``OP_NETWORK_ADD``
  Add a network to Ganeti

  :directory: network-add
  :pre-execution: master node
  :post-execution: master node

``OP_NETWORK_REMOVE``
  Remove a network from Ganeti

  :directory: network-remove
  :pre-execution: master node
  :post-execution: master node

``OP_NETWORK_SET_PARAMS``
  Modify a network

  :directory: network-modify
  :pre-execution: master node
  :post-execution: master node

For connect/disconnect operations use existing:

``OP_GROUP_SET_PARAMS``
  Modify a nodegroup

  :directory: group-modify
  :pre-execution: master node
  :post-execution: master node

Hook variables
^^^^^^^^^^^^^^

During instance related operations:

``INSTANCE_NICn_NETWORK``
  The friendly name of the network

During network related operations:

``NETWORK_NAME``
  The friendly name of the network

``NETWORK_SUBNET``
  The ip range of the network

``NETWORK_GATEWAY``
  The gateway of the network

During nodegroup related operations:

``GROUP_NETWORK``
  The friendly name of the network

``GROUP_NETWORK_MODE``
  The mode (bridged or routed) of the netparams

``GROUP_NETWORK_LINK``
  The link of the netparams

Backend changes
+++++++++++++++

To keep the hypervisor-visible changes to a minimum, and maintain
compatibility with the existing network configuration scripts, the
instance's hypervisor configuration will have host-level mode and link
replaced by the *connectivity mode* and *host interface* (netparams) of
the given network on the current node group.

Network configuration scripts detect if a NIC is assigned to a Network
by the presence of the new environment variable:

Network configuration script variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``NETWORK``
  The friendly name of the network

Conflicting IPs
+++++++++++++++

To ensure IP uniqueness inside a nodegroup, we introduce the term
``conflicting ips``. Conflicting IPs occur: (a) when creating a
networkless NIC with IP contained in a network already connected to the
instance's nodegroup  (b) when connecting/disconnecting a network
to/from a nodegroup and at the same time instances with IPs inside the
network's range still exist. Conflicting IPs produce prereq errors.

Handling of conflicting IP with --force option:

For case (a) reserve the IP and assign the NIC to the Network.
For case (b) during connect same as (a), during disconnect release IP and
reset NIC's network parameter to None


Userland interface
++++++++++++++++++

A new client script is introduced, ``gnt-network``, which handles
network-related configuration in Ganeti.

Network addition/deletion
^^^^^^^^^^^^^^^^^^^^^^^^^
::

 gnt-network add --network=192.168.100.0/28 --gateway=192.168.100.1 \
                 --network6=2001:db8:2ffc::/64 --gateway6=2001:db8:2ffc::1 \
                 --add-reserved-ips=192.168.100.10,192.168.100.11 net100
  (Checks for already exising name and valid IP values)
 gnt-network remove network_name
  (Checks if not connected to any nodegroup)


Network modification
^^^^^^^^^^^^^^^^^^^^
::

 gnt-network modify --gateway=192.168.100.5 net100
  (Changes the gateway only if ip is available)
 gnt-network modify --add-reserved-ips=192.168.100.11 net100
  (Adds externally reserved ip)
 gnt-network modify --remove-reserved-ips=192.168.100.11 net100
  (Removes externally reserved ip)


Assignment to node groups
^^^^^^^^^^^^^^^^^^^^^^^^^
::

 gnt-network connect net100 nodegroup1 bridged br100
  (Checks for existing bridge among nodegroup)
 gnt-network connect net100 nodegroup2 routed rt_table
  (Checks for conflicting IPs)
 gnt-network disconnect net101 nodegroup1
  (Checks for conflicting IPs)


Network listing
^^^^^^^^^^^^^^^
::

 gnt-network list

 Network      Subnet           Gateway       NodeGroups GroupList
 net100       192.168.100.0/28 192.168.100.1          1 default(bridged, br100)
 net101       192.168.101.0/28 192.168.101.1          1 default(routed, rt_tab)

Network information
^^^^^^^^^^^^^^^^^^^
::

 gnt-network info testnet1

 Network name: testnet1
  subnet: 192.168.100.0/28
  gateway: 192.168.100.1
  size: 16
  free: 10 (62.50%)
  usage map:
        0 XXXXX..........X                                                 63
          (X) used    (.) free
  externally reserved IPs:
    192.168.100.0, 192.168.100.1, 192.168.100.15
  connected to node groups:
    default(bridged, br100)
  used by 3 instances:
    test1 : 0:192.168.100.4
    test2 : 0:192.168.100.2
    test3 : 0:192.168.100.3


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
