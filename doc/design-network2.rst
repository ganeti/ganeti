============================
Network Management (revised)
============================

.. contents:: :depth: 4

This is a design document detailing how to extend the existing network
management and make it more flexible and able to deal with more generic
use cases.


Current state and shortcomings
------------------------------

Currently in Ganeti, networks are tightly connected with IP pools,
since creation of a network implies the existence of one subnet
and the corresponding IP pool. This design does not allow common
scenarios like:

- L2 only networks
- IPv6 only networks
- Networks without an IP pool
- Networks with an IPv6 pool
- Networks with multiple IP pools (alternative to externally reserving
  IPs)

Additionally one cannot have multiple IP pools inside one network.
Finally, from the instance perspective, a NIC cannot get more than one
IPs (v4 and v6).


Proposed changes
----------------

In order to deal with the above shortcomings, we propose to extend
the existing networks in Ganeti and support:

a) Networks with multiple subnets
b) Subnets with multiple IP pools
c) NICs with multiple IPs from various subnets of a single network

These changes bring up some design and implementation issues that we
discuss in the following sections.

Semantics
++++++++++

Quoting the initial network management design doc "an IP pool consists
of two bitarrays. Specifically the ``reservations`` bitarray which holds
all IP addresses reserved by Ganeti instances and the ``external
reservations`` bitarray with all IPs that are excluded from the IP pool
and cannot be assigned automatically by Ganeti to instances (via
ip=pool)".

Without violating those semantics, here, we clarify the following
definitions.

**network**: A cluster level taggable configuration object with a
user-provider name, (e.g. network1, network2), UUID and MAC prefix.

**L2**: The `mode` and `link` with which we connect a network to a
nodegroup. A NIC attached to a network will inherit this info, just like
connecting an Ethernet cable to a physical NIC. In this sense we only
have one L2 info per NIC.

**L3**: A CIDR and a gateway related to the network. Since a NIC can
have multiple IPs on the same cable each network can have multiple L3
info with the restriction that they do not overlap with each other.
The gateway is optional (just like with current implementation). No
gateway can be used for private networks that do not have a default
route.

**subnet**: A subnet is the above L3 info plus some additional information
(see below).

**ip**: A valid IP should reside in a network's subnet, and should not
be used by more than one instance. An IP can be either obtained dynamically
from a pool or requested explicitly from a subnet (or a pool).

**range**: Sequential IPs inside one subnet calculated either from the
first IP and a size (e.g. start=192.0.2.10, size=10) or the first IP and
the last IP (e.g. start=192.0.2.10, end=192.0.2.19). A single IP can
also be thought of as an IP range with size=1 (see configuration
changes).

**reservations**: All IPs that are used by instances in the cluster at
any time.

**external reservations**: All IPs that are supposed to be reserved
by the admin for either some external component or specific instances.
If one instance requests an external IP explicitly (ip=192.0.2.100),
Ganeti will allow the operation only if ``--force`` is given. Still, the
admin can externally reserve an IP that is already in use by an
instance, as happens now. This helps to reserve an IP for future use and
at the same time prevent any possible race between the instance that
releases this IP and another that tries to retrieve it.

**pool**: A (range, reservations, name) tuple from which instances can
dynamically obtain an IP. Reservations is a bitarray with
length the size of the range, and is needed so that we know which IPs
are available at any time without querying all instances. The use of
name is explained below. A subnet can have multiple pools.


Split L2 from L3
++++++++++++++++

Currently networks in Ganeti do not separate L2 from L3. This means
that one cannot use L2 only networks. The reason is because the CIDR
(passed currently with the ``--network`` option) and the derived IP pool
are mandatory. This design makes L3 info optional. This way we can have
an L2 only network just by connecting a Ganeti network to a nodegroup
with the desired `mode` and `link`. Then one could add one or more subnets
to the existing network.


Multiple Subnets per Network
++++++++++++++++++++++++++++

Currently the IPv4 CIDR is mandatory for a network. Also a network can
obtain at most one IPv4 CIDR and one IPv6 CIDR. These restrictions will
be lifted.

This design doc introduces support for multiple subnets per network. The
L3 info will be moved inside the subnet. A subnet will have a `name` and
a `uuid` just like NIC and Disk config objects. Additionally it will contain
the `dhcp` flag which is explained below, and the `pools` and `external`
fields which are mentioned in the next section. Only the `cidr` will be
mandatory.

Any subnet related actions will be done via the new ``--subnet`` option.
Its syntax will be similar to ``--net``.

The network's subnets must not overlap with each other. Logic will
validate any operations related to reserving/releasing of IPs and check
whether a requested IP is included inside one of the network's subnets.
Just like currently, the L3 info will be exported to NIC configuration
hooks and scripts as environment variables. The example below adds
subnets to a network:

::

  gnt-network modify --subnet add:cidr=10.0.0.0/24,gateway=10.0.0.1,dhcp=true net1
  gnt-network modify --subnet add:cidr=2001::/64,gateway=2001::1,dhcp=true net1

To remove a subnet from a network one should use:

::

  gnt-network modify --subnet some-ident:remove network1

where some-ident can be either a CIDR, a name or a UUID. Ganeti will
allow this operation only if no instances use IPs from this subnet.

Since DHCP is allowed only for a single CIDR on the same cable, the
subnet must have a `dhcp` flag. Logic must not allow more that one
subnets of the same version (4 or 6) in the same network to have DHCP enabled.
To modify a subnet's name or the dhcp flag one could use:

::

  gnt-network modify --subnet some-ident:modify,dhcp=false,name=foo network1

This would search for a registered subnet that matches the identifier,
disable DHCP on it and change its name.
The ``dhcp`` parameter is used only for validation purposes and does not
make Ganeti starting a DHCP service. It will just be exported to
external scripts (ifup and hooks) and handled accordingly.

Changing the CIDR or the gateway of a subnet should also be supported.

::

  gnt-network modify --subnet some-ident:modify,cidr=192.0.2.0/22 net1
  gnt-network modify --subnet some-ident:modify,cidr=192.0.2.32/28 net1
  gnt-network modify --subnet some-ident:modify,gateway=192.0.2.40 net1

Before expanding a subnet logic should should check for overlapping
subnets. Shrinking the subnet should be allowed only if the ranges
that are about to be trimmed are not included either in pool
reservations or external ranges.


Multiple IP pools per Subnet
++++++++++++++++++++++++++++

Currently IP pools are automatically created during network creation and
include the whole subnet. Some IPs can be excluded from the pool by
passing them explicitly with ``--add-reserved-ips`` option.

Still for IPv6 subnets or even big IPv4 ones this might be insufficient.
It is impossible to have two bitarrays for a /64 prefix. Even for IPv4
networks a /20 subnet currently requires 8K long bitarrays. And the
second 4K is practically useless since the external reservations are way
less than the actual reservations.

This design extract IP pool management from the network logic, and pools
will become optional. Currently the pool is created based on the
network's CIDR. With multiple subnets per network, we should be able to
create and add IP pools to a network (and eventually to the
corresponding subnet). Each pool will have an optional user friendly
`name` so that the end user can refer to it (see instance related
operations).

The user will be able to obtain dynamically an IP only if we have
already defined a pool for a network's subnet. One would use ``ip=pool``
for the first available IP of the first available pool, or
``ip=some-pool-name`` for the first available IP of a specific pool.

Any pool related actions will be done via the new ``--pool`` option.

In order to add a pool a relevant subnet should pre-exist. Overlapping
pools won't be allowed. For example:

::

  gnt-network modify --pool add:192.0.2.10-192.0.2.100,name=pool1 net1
  gnt-network modify --pool add:10.0.0.7-10.0.0.20 net1
  gnt-network modify --pool add:10.0.0.100 net1

will first parse and find the ranges. Then for each range, Ganeti will
try to find a matching subnet meaning that a pool must be a subrange of
the subnet. If found, the range with empty reservations will be appended
to the list of the subnet's pools. Moreover, logic must be added to
reserve the IPs that are currently in use by instances of this network.

Adding a pool can be easier if we associate it directly with a subnet.
For example on could use the following shortcuts:

::

  gnt-network modify --subnet add:cidr=10.0.0.0/27,pool net1
  gnt-network modify --pool add:subnet=some-ident
  gnt-network modify --pool add:10.0.0.0/27 net1

During pool removal, logic should be added to split pools if ranges
given overlap existing ones. For example:

::

  gnt-network modify --pool remove:192.0.2.20-192.0.2.50 net1

will split the pool previously added (10-100) into two new ones;
10-19 and 51-100. The corresponding bitarrays will be trimmed
accordingly. The name will be preserved.

The same things apply to external reservations. Just like now,
modifications will take place via the ``--add|remove-reserved-ips``
option. Logic must be added to support IP ranges.

::

  gnt-network modify --add-reserved-ips 192.0.2.20-192.0.2.50 net1


Based on the aforementioned we propose the following changes:

1) Change the IP pool representation in config data.

  Existing `reservations` and `external_reservations` bitarrays will be
  removed. Instead, for each subnet we will have:

  * `pools`: List of (IP range, reservations bitarray) tuples.
  * `external`: List of IP ranges

  For external ranges the reservations bitarray is not needed
  since this will be all 1's.

  A configuration example could be::

    net1 {
      subnets [
        uuid1 {
            name: subnet1
            cidr: 192.0.2.0/24
            pools: [
              {range:Range(192.0.2.10, 192.0.2.15), reservations: 00000, name:pool1}
              ]
            reserved: [192.0.2.15]
            }
        uuid2  {
            name: subnet2
            cidr: 10.0.0.0/24
            pools: [
              {range:10.0.0.8/29, reservations: 00000000, name:pool3}
              {range:10.0.0.40-10.0.0.45, reservations: 000000, name:pool3}
              ]
            reserved: [Range(10.0.0.8, 10.0.0.15), 10.2.4.5]
            }
        ]
    }

  Range(start, end) will be some json representation of an IPRange().
  We decide not to store external reservations as pools (and in the
  same list) since we get the following advantages:

 - Keep the existing semantics for pools and external reservations.

 - Each list has similar entries: one has pools the other has ranges.
   The pool must have a bitarray, and has an optional name. It is
   meaningless to add a name and a bitarray to external ranges.

 - Each list must not have overlapping ranges. Still external
   reservations can overlap with pools.

 - The --pool option supports add|remove|modify command just like
   `--net` and `--disk` and operate on single entities (a restriction that
   is not needed for external reservations).

 - Another thing, and probably the most important, is that in order to
   get the first available IP, only the reserved list must be checked for
   conflicts. The ipaddr.summarize_address_range(first, last) could be very
   helpful.


2) Change the network module logic.

  The above changes should be done in the network module and be transparent
  to the rest of the Ganeti code. If a random IP from the networks is
  requested, Ganeti searches for an available IP from the first pool of
  the first subnet. If it is full it gets to the next pool. Then to the
  next subnet and so on. Of course the `external` IP ranges will be
  excluded. If an IP is explicitly requested, Ganeti will try to find a
  matching subnet. Its pools and external will be checked for
  availability. All this logic will be extracted in a separate class
  with helper methods for easier manipulation of IP ranges and
  bitarrays.

  Bitarray processing can be optimized too. The usage of bitarrays will
  be reduced since (a) we no longer have `external_reservations` and (b)
  pools will have shorter bitarrays (i.e. will not have to cover the whole
  subnet). Besides that, we could keep the bitarrays in memory, so that
  in most cases (e.g. adding/removing reservations, querying), we don't
  keep converting strings to bitarrays and vice versa. Also, the Haskell
  code could as well keep this in memory as a bitarray, and validate it
  on load.

3) Changes in config module.

  We should not have instances with the same IP inside the same network.
  We introduce _AllIPs() helper config method that will hold all existing
  (IP, network) tuples. Config logic will check this list as well
  before passing it to TemporaryReservationManager.

4) Change the query mechanism.

  Since we have more that one subnets the new `subnets` field will
  include a list of:

  * cidr: IPv4 or IPv6 CIDR
  * gateway: IPv4 or IPv6 address
  * dhcp: True or False
  * name: The user friendly name for the subnet

  Since we want to support small pools inside big subnets, current query
  results are not practical as far as the `map` field is concerned. It
  should be replaced with the new `pools` field for each subnet, which will
  contain:

  * start: The first IP of the pool
  * end: The last IP of the pool
  * map: A string with 'X' for reserved IPs (either external or not) and
    with '.' for all available ones inside the pool



Multiple IPs per NIC
++++++++++++++++++++

Currently IP is a simple string inside the NIC object and there is a
one-to-one mapping between the `ip` and the `network` slots. The whole
logic behind this is that a NIC belongs to a network (cable) and
inherits its mode and link. This rational will not change.

Since this design adds support for multiple subnets per network, a NIC
must be able to obtain multiple IPs from various subnets of the same
network. Thus we change the `ip` slot into list.

We introduce a new `ipX` attribute. For backwards compatibility `ip`
will denote `ip0`.
During instance related operations one could use something like:

::

  gnt-instance add --net 0:ip0=192.0.2.4,ip1=pool,ip2=some-pool-name,network=network1 inst1
  gnt-instance add --net 0:ip=pool,network1 inst1


This will be parsed, converted to a proper list (e.g. ip = [192.0.2.4,
"pool", "some-pool-name"]) and finally passed to the corresponding opcode.
Based on the previous example, here the first IP will match subnet1, the
second IP will be retrieved from the first available pool of the first
available subnet, and the third from the pool with the some-pool name.

During instance modification, the `ip` option will refer to the first IP
of the NIC, whereas the `ipX` will refer to the X'th IP. As with NICs
we start counting from 0 so `ip1` will refer to the second IP. For example
one should pass:

::

 --net 0:modify,ip1=1.2.3.10

to change the second IP of the first NIC to 1.2.3.10,

::

  --net -1:add,ip0=pool,ip1=1.2.3.4,network=test

to add a new NIC with two IPs, and

::

  --net 1:modify,ip1=none

to remove the second IP of the second NIC.


Configuration changes
---------------------

IPRange config object:
  Introduce new config object that will hold ranges needed by pools, and
  reservations. It will be either a tuple of (start, size, end) or a
  simple string. The `end` is redundant and can derive from start and
  size in runtime, but will appear in the representation for readability
  and debug reasons.

Pool config object:
  Introduce new config object to represent a single subnet's pool. It
  will have the `range`, `reservations`, `name` slots. The range slot
  will be an IPRange config object, the reservations a bitarray and the
  name a simple string.

Subnet config object:
  Introduce new config object with slots: `name`, `uuid`, `cidr`,
  `gateway`, `dhcp`, `pools`, `external`. Pools is a list of Pool config
  objects. External is a list of IPRange config objects. All ranges must
  reside inside the subnet's CIDR. Only `cidr` will be mandatory. The
  `dhcp` attribute will be False by default.

Network config objects:
  The L3 and the IP pool representation will change. Specifically all
  slots besides `name`, `mac_prefix`, and `tag` will be removed. Instead
  the slot `subnets` with a list of Subnet config objects will be added.

NIC config objects:
  NIC's network slot will be removed and the `ip` slot will be modified
  to a list of strings.

KVM runtime files:
  Any change done in config data must be done also in KVM runtime files.
  For this purpose the existing _UpgradeSerializedRuntime() can be used.


Exported variables
------------------

The exported variables during instance related operations will be just
like Linux uses aliases for interfaces. Specifically:

``IP:i`` for the ith IP.

``NETWORK_*:i`` for the ith subnet. * is SUBNET, GATEWAY, DHCP.

In case of hooks those variables will be prefixed with ``INSTANCE_NICn``
for the nth NIC.


Backwards Compatibility
-----------------------

The existing networks representation will be internally modified.
They will obtain one subnet, and one pool with range the whole subnet.

During `gnt-network add` if the deprecated ``--network`` option is passed
will still create a network with one subnet, and one IP pool with the
size of the subnet. Otherwise ``--subnet`` and ``--pool`` options
will be needed.

The query mechanism will also include the deprecated `map` field. For the
newly created network this will contain only the mapping of the first
pool. The deprecated `network`, `gateway`, `network6`, `gateway6` fields
will point to the first IPv4 and IPv6 subnet accordingly.

During instance related operation the `ip` argument of the ``--net``
option will refer to the first IP of the NIC.

Hooks and scripts will still have the same environment exported in case
of single IP per NIC.

This design allows more fine-grained configurations which in turn yields
more flexibility and a wider coverage of use cases. Still basic cases
(the ones that are currently available) should be easy to set up.
Documentation will be enriched with examples for both typical and
advanced use cases of gnt-network.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
