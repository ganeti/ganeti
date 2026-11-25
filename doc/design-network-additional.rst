=========================================================
Layer 3 networks, shared addresses and stateless pools
=========================================================

:Created: 2026-Oct-22
:Status: Draft
:Ganeti-Version: TBD

.. contents:: :depth: 4

This design document proposes a set of incremental changes to Ganeti's
network management (``gnt-network``) that remove the current size
limits of address pools, enable IPv6 address management, allow a NIC to
carry addresses from more than one network, and allow selected
addresses to be assigned to several instances at the same time
(service IPs for anycast/ECMP or failover setups).

The changes are additive. Existing networks, NICs, opcodes and RAPI
clients keep their current behaviour unless they opt into the new
fields.

Related issues
==============

The following open issues are resolved by this design:

- `#453 <https://github.com/ganeti/ganeti/issues/453>`_: Network
  implementation and bitarrays (part 2 removes the bitmaps).
- `#667 <https://github.com/ganeti/ganeti/issues/667>`_: gnt-network
  add's mandatory --network option hinders usage of IPv6 only (part 1).
- `#688 <https://github.com/ganeti/ganeti/issues/688>`_: Can't add
  IPv6-only VM to gnt-network (parts 1 and 2).
- `#1551 <https://github.com/ganeti/ganeti/issues/1551>`_: gnt-network:
  do not require to specify a --network x.x.x.x/y (part 1).

The following issues are addressed in part:

- `#258 <https://github.com/ganeti/ganeti/issues/258>`_: multiple IP
  addresses and subnet routing for instances in routed mode. Part 3
  allows several IPv4 and IPv6 addresses per NIC and installs host
  routes for them; routing whole prefixes to an instance is not
  covered.
- `#1305 <https://github.com/ganeti/ganeti/issues/1305>`_: ranges in
  ``--add-reserved-ips``. Reservations are stored as ranges (part 2);
  accepting ranges on the command line is an open question.
- `#744 <https://github.com/ganeti/ganeti/issues/744>`_: restrict the
  pool to an address range. With range reservations the addresses
  outside the range can be reserved with two entries instead of one
  per address.


Current state and shortcomings
==============================

Address pools are dense bitmaps
-------------------------------

Every network carries an ``AddressPool`` (``lib/network.py``, and its
Haskell counterpart in ``Ganeti.Network``) consisting of two bitmaps,
``reservations`` and ``ext_reservations``, with one bit per address of
the network. Both bitmaps are serialized into ``config.data`` as
strings of ``0`` and ``1`` characters.

This has several consequences:

- The configuration size grows linearly with the size of the network.
  A /16 already adds roughly 128 KiB per network to a file that is
  rewritten and distributed to all master candidates on every change.
  To keep this bounded, network sizes are restricted to the range
  between ``IPV4_NETWORK_MAX_SIZE`` (/16) and ``IPV4_NETWORK_MIN_SIZE``
  (/30).

- IPv6 networks cannot be represented at all (a /64 would need 2^64
  bits). ``network6`` and ``gateway6`` are therefore pure metadata: they
  are passed to hooks and ifup scripts, but there is no allocation and
  no conflict checking for IPv6 addresses.

- The bitmap duplicates information that is already present in the
  configuration (the ``ip`` of every NIC). The two can get out of sync,
  which is why ``gnt-cluster verify`` has to check their consistency.

- Operations such as allocating a free address, counting free addresses
  or rendering the ``map`` query field walk the bitmap linearly.

Small prefixes are not supported
--------------------------------

Point-to-point and single-address networks are common in routed
setups:

- /31 (RFC 3021) and /127 (RFC 6164) for transfer and peering networks,
- /32 and /128 for single service addresses.

These are rejected by the size limits above, and the pool logic always
reserves the network and broadcast addresses, which is wrong for these
prefix lengths.

A NIC belongs to exactly one network and has exactly one address
----------------------------------------------------------------

A NIC has a single ``ip`` and a single ``network``. Common setups need
more than that, for example:

- a public IPv6 address, a ULA address and a fixed link-local address
  on the same interface,
- an IPv6-only host address plus an IPv4 service address that is
  announced via MP-BGP with an IPv6 next hop (RFC 8950).

Addresses cannot be shared between instances
--------------------------------------------

An address of a network can be used by at most one NIC. Assigning the
same address to several instances (anycast/ECMP, or failover setups
where the routing layer decides which instance is active) is only
possible by disabling conflict checks with ``--no-conflicts-check``.
In that case Ganeti does not know the address is shared; when one of
the instances releases it, the address is returned to the pool and can
be handed out to an unrelated instance.

Layer 2 and layer 3 are mixed in one object
-------------------------------------------

A network combines layer 2 properties (``mac_prefix`` on the network,
``mode``/``link``/``vlan`` in the netparams of ``gnt-network
connect``) with layer 3 properties (prefixes, gateways, reservations).
As long as a NIC references exactly one network this is unambiguous.
Once a NIC can reference several networks it is not clear which MAC
prefix and which link/VLAN apply.


Proposed changes
================

The proposal consists of four parts that can be implemented and merged
independently, in the order given below.

Part 1: Small prefixes and address-less networks
------------------------------------------------

Prefix lengths
~~~~~~~~~~~~~~

The minimum network size is changed to /32 for IPv4 and /128 for IPv6.
The set of addresses that are implicitly reserved ("system
reservations") depends on the prefix length:

=========  ===============  ==========================================
Family     Prefix length    System reservations
=========  ===============  ==========================================
IPv4       /0 - /30         network address, broadcast address
IPv4       /31, /32         none
IPv6       /0 - /126        subnet-router anycast address (``::``)
IPv6       /127, /128       none
=========  ===============  ==========================================

The gateway, if set, is reserved in addition, as today.

Gateways
~~~~~~~~

For /31 and /127 the gateway is the peer address and is handled as
today. For /32 and /128 there is no room for an in-network gateway;
the gateway becomes optional for these networks and may be an
off-network, on-link address (e.g. ``fe80::1``).

Optional prefixes
~~~~~~~~~~~~~~~~~

The IPv4 prefix (``--network``) is no longer mandatory. A network may
have an IPv4 prefix, an IPv6 prefix, both, or (see part 3) none at all.

Counting
~~~~~~~~

Free and reserved counts are computed with plain integer arithmetic
on the prefix and the reservations, so that tiny prefixes never
produce negative or off-by-two results.

Part 2: Stateless address pools
-------------------------------

The ``reservations`` and ``ext_reservations`` bitmaps are removed from
the configuration. A network only stores configuration; the usage of
its addresses is derived.

Stored state
~~~~~~~~~~~~

Reserved addresses are stored as a sorted list of disjoint, inclusive
ranges, each with a kind (see part 4)::

  "reserved_ranges": [
    ["2001:db8:100::1",  "2001:db8:100::ff",  "extern"],
    ["2001:db8:100::80:0", "2001:db8:100::80:0", "shared"]
  ]

Adding and removing reservations merges and splits ranges; adjacent
ranges are only merged if they have the same kind.

Derived state
~~~~~~~~~~~~~

An address of a network is *in use* if any NIC references it in that
network, either as its primary ``ip`` or as one of its additional
addresses (part 3). An address is *free* if it is inside one of the
network's prefixes and is not a system reservation, not reserved
(``extern`` or ``shared``), not in use, and not temporarily reserved.

Temporary reservations for jobs in flight continue to be handled in
memory by WConfD (``Ganeti.WConfd.TempRes``), as today.

WConfD keeps an in-memory index (network to sorted list of used
addresses) that is rebuilt on configuration load and updated on
configuration changes. The index is never written to disk. Allocation
(``ip=pool``) returns the lowest free address by walking the sorted
lists of reservations and used addresses, which is O(number of used
addresses + number of ranges) and independent of the prefix size.

Consequences
~~~~~~~~~~~~

- ``IPV4_NETWORK_MAX_SIZE`` is removed; networks of any size are
  supported.
- IPv6 networks get a real pool: allocation (``ip=pool``), conflict
  checks and reservations work the same as for IPv4.
- ``--add-reserved-ips`` and ``--remove-reserved-ips`` accept IPv4 and
  IPv6 addresses, also mixed in one list. Each address is matched by
  its family to the network's IPv4 or IPv6 prefix and rejected if it
  is in neither. No separate ``--add-reserved-ips6`` or
  ``--remove-reserved-ips6`` options are introduced, and the existing
  ``external_reservations`` query field lists addresses of both
  families.
- ``gnt-cluster verify`` no longer checks bitmap/NIC consistency.
  Instead it checks that no address appears more than once in a
  network unless it is reserved as ``shared`` (see part 4).
- The ``free_count`` and ``reserved_count`` query fields are computed
  from the derived state. The ``map`` query field is kept for small
  networks and returns an error (or is truncated) above a size limit,
  e.g. 4096 addresses.

Part 3: Network types and additional addresses
----------------------------------------------

Network types
~~~~~~~~~~~~~

A new network attribute ``type`` is introduced with two values. The
names state which layers a network describes, so that users can tell
from the type alone whether a network can serve as a NIC's segment.

``layer2+layer3`` (default)
  Behaves exactly as networks do today: it carries layer 2 information
  (``mac_prefix`` and the netparams of ``gnt-network connect``:
  ``mode``, ``link``, ``vlan``) and optionally layer 3 information
  (prefixes, gateways, reservations). The layer 3 part is optional; a
  network of this type without any prefix is a pure layer 2 segment.

``layer3``
  A pure layer 3 network. It has prefixes, gateways and reservations.
  It may not have a ``mac_prefix``. Its netparams are never used;
  connecting it to a node group is optional and only restricts the
  node groups in which instances may use it. If it is connected, the
  netparams must be empty.

This keeps layer 2 and layer 3 apart without introducing a new object
type: the primary network of a NIC defines the segment, ``layer3``
networks only contribute addresses.

The type of a network can only be changed while no NIC references it.

NIC additional addresses
~~~~~~~~~~~~~~~~~~~~~~~~

A NIC gets a new attribute ``additional``, a list of addresses that
each reference a ``layer3`` network::

  {
    "mac": "aa:00:01:12:34:56",
    "network": "<uuid of seg-pub>",
    "ip": null,
    "additional": [
      {"ip": "2001:db8:100::42",   "network": "<uuid of pub6>"},
      {"ip": "fd12:3456:789a::42", "network": "<uuid of ula>"},
      {"ip": "fe80::2",            "network": "<uuid of ll>"},
      {"ip": "198.51.100.10",      "network": "<uuid of vip>"}
    ],
    "nicparams": {...}
  }

Rules:

- The NIC's primary ``network`` must be of type ``layer2+layer3``.
  Networks referenced in ``additional`` must be of type ``layer3``.
- Every address must be inside a prefix of the same family of its
  network.
- If the primary network has no prefix of the family of the NIC's
  ``ip``, setting ``ip`` is rejected.
- Uniqueness is enforced per network, except for addresses reserved as
  ``shared`` (part 4).
- If a ``layer3`` network is connected to node groups, the instance's
  node group must be among them.
- A network cannot be removed while any NIC references it, including
  through ``additional``.

Opcodes, RAPI and CLI
~~~~~~~~~~~~~~~~~~~~~

The NIC dictionaries of ``OpInstanceCreate`` and
``OpInstanceSetParams`` accept a new optional key ``additional``. Its
absence means "no additional addresses" on creation and "unchanged" on
modification. RAPI exposes the same key in the NIC objects, and new
query fields expose it (e.g. ``nic.additional/N``).

On the command line the key takes a ``+``-separated list of
``network:address`` pairs, where ``address`` is either an address or
``pool``. The pair is split at the first colon only, so IPv6 addresses
can be written as usual::

  gnt-instance add ... \
    --net 0:network=seg-pub,additional=pub6:pool+ula:pool+ll:fe80::2+vip:198.51.100.10 \
    inst1.example.com

  gnt-instance modify --net 0:modify,additional=pub6:pool+ll:fe80::2 inst1.example.com

On modification the given list replaces the current one; addresses
that are no longer referenced are released.

``gnt-network add`` and ``gnt-network modify`` get a ``--type`` option
taking ``layer2+layer3`` or ``layer3``. ``gnt-network info`` lists
instances that use the network through ``additional`` as well.

Hooks and ifup scripts
~~~~~~~~~~~~~~~~~~~~~~

The existing variables (``INSTANCE_NIC%d_IP``,
``INSTANCE_NIC%d_NETWORK_*``) are unchanged and describe the primary
network. ``INSTANCE_NIC%d_IP_SHARED`` is added and states whether the
primary ``ip`` is a shared address. New variables describe the
additional addresses::

  INSTANCE_NIC0_ADDITIONAL_COUNT=4
  INSTANCE_NIC0_ADDITIONAL0_IP=2001:db8:100::42
  INSTANCE_NIC0_ADDITIONAL0_SHARED=False
  INSTANCE_NIC0_ADDITIONAL0_NETWORK_NAME=pub6
  INSTANCE_NIC0_ADDITIONAL0_NETWORK_UUID=...
  INSTANCE_NIC0_ADDITIONAL0_NETWORK_SUBNET6=2001:db8:100::/64
  INSTANCE_NIC0_ADDITIONAL0_NETWORK_GATEWAY6=fe80::1
  ...

The same variables are exported to the NIC ifup scripts. In routed
mode, the default scripts (``tools/net-common``) install a host route
(/32 or /128) via the tap device for every additional address, in the
same way as for the primary ``ip``.

Part 4: Shared reservations
---------------------------

Instead of a new network attribute, sharing is expressed per address
by extending the existing reservation mechanism. Every reservation has
a kind:

``extern`` (default)
  The current behaviour of external reservations: the address is
  blocked and can neither be allocated by ``ip=pool`` nor assigned
  explicitly to a NIC.

``shared``
  The address may be assigned explicitly to any number of NICs, as
  primary ``ip`` or in ``additional``. It is never handed out by
  ``ip=pool``.

CLI
~~~

``--add-reserved-ips`` of ``gnt-network add`` and ``gnt-network
modify`` keeps its comma-separated list format. Each list element is
either a plain address or ``address=kind``, where ``kind`` is
``extern`` or ``shared``. A plain address is ``extern``, so existing
invocations keep their meaning. The ``=`` separator does not collide
with IPv6 notation::

  # unchanged: two external reservations
  gnt-network modify --add-reserved-ips=192.0.2.1,192.0.2.2 net1

  # explicit kinds, mixed with a plain (extern) address
  gnt-network modify \
    --add-reserved-ips=198.51.100.10=shared,198.51.100.11=extern,198.51.100.12 net1

  # fixed link-local address used on every NIC
  gnt-network modify --add-reserved-ips=fe80::2=shared ll

An unknown kind, or an element with more than one ``=``, is rejected.

``--remove-reserved-ips`` takes plain addresses, as today, regardless
of their kind. Adding an address that is already reserved changes its
kind.

Rules
~~~~~

- An address that is in use by a NIC can be reserved as ``shared``
  (this is how an existing host address becomes a service address). It
  cannot be reserved as ``extern``.
- A ``shared`` reservation cannot be removed or changed to ``extern``
  while more than one NIC references the address. If exactly one NIC
  references it, it becomes an ordinary in-use address of that NIC.
- No ownership is stored. Which NICs use a shared address is derived
  from the configuration (part 2), so there is no reference count that
  could become inconsistent.
- Shared addresses are allowed in both network types. In bridged mode,
  using the same address on several NICs of one segment leads to
  address conflicts on the link; this is the administrator's
  responsibility, as it is with ``--no-conflicts-check`` today.

The query fields of networks get ``shared_reservations`` next to the
existing ``external_reservations``.

Typical uses:

- service addresses for anycast/ECMP or routing-based failover, either
  in a dedicated /32 or /128 ``layer3`` network or as single addresses
  inside an existing network,
- link-local addresses (``fe80::/64``) that are fixed and identical on
  every NIC, e.g. as BGP unnumbered peer addresses.

Ganeti does not decide which instance actually serves a shared address.
Announcing, health checking and failover are left to the routing layer
(e.g. BGP speakers on the instances or nodes), which can read the
addresses from the hook and ifup variables. To keep instances that
share an address on different nodes, the existing exclusion tags of
the htools can be used.


Configuration upgrade and downgrade
===================================

Upgrade (``cfgupgrade``):

- add ``type = "layer2+layer3"`` to every network,
- convert ``ext_reservations`` into ``reserved_ranges`` of kind
  ``extern``, excluding the system reservations and the gateway,
- drop ``reservations`` and ``ext_reservations``,
- add an empty ``additional`` list to every NIC.

Downgrade:

- refuse if any network is of type ``layer3``, has a ``shared``
  reservation, has no IPv4 prefix, or has a prefix outside the old size
  limits,
- refuse if any NIC has a non-empty ``additional`` list,
- otherwise regenerate the bitmaps from the NICs and the ``extern``
  reservations, and drop the new attributes.


Implementation notes
====================

- Python and Haskell must be changed together for parts 2 to 4, since
  WConfD owns the configuration and performs IP reservations
  (``Ganeti.Objects``, ``Ganeti.Network``, ``Ganeti.WConfd.TempRes``,
  ``lib/network.py``, ``lib/objects.py``, the network and instance
  LUs, ``lib/tools/cfgupgrade.py``).
- The constants for the network size limits are defined in the Haskell
  constants module and generated for Python; they need to be updated
  there.
- The parser for ``--add-reserved-ips`` needs to split each element at
  ``=`` and validate the kind; ``--remove-reserved-ips`` is unchanged.
- Tests: the Python unit tests for ``lib/network.py`` and the network
  and instance LUs, and the QuickCheck generators and properties for
  network and NIC objects on the Haskell side.
- htools are not affected.


Alternatives considered
=======================

Interval-based pool instead of removing the pool
------------------------------------------------

Replacing the bitmaps with a sorted list of used intervals would also
remove the size limit. It still duplicates information that is already
in the NICs and therefore still needs consistency checks. Deriving the
usage from the NICs avoids both.

A network-wide ``shared`` flag
------------------------------

Marking whole networks as shared needs a new network attribute and
forces every service address into its own network. Per-address
reservation kinds reuse the existing reservation mechanism and CLI
option, and allow service addresses inside ordinary networks.

A separate segment object
-------------------------

Splitting a network into a layer 2 *segment* object and a layer 3
*network* object would be the cleanest model, but it introduces a new
object type, new commands and new RAPI resources. The ``type``
attribute proposed here maps one-to-one onto that model, so such a
split remains possible later without invalidating configurations.

Service objects with modes and priorities
-----------------------------------------

Modelling services explicitly (anycast vs. failover, member priorities,
mapping to BGP attributes) would make Ganeti responsible for routing
policy and, for failover, for runtime state it cannot observe reliably.
Shared reservations only allow the assignment; routing policy stays
outside Ganeti.


Open questions
==============

- Older Ganeti versions had a ``--network-type`` option with a different
  meaning. Is reusing the name ``type`` acceptable, or should the
  attribute get a different name?
- Should ``--add-reserved-ips`` also accept ranges now that
  reservations are stored as ranges (e.g. ``198.51.100.16-198.51.100.31=shared``)?
- Size limit and behaviour of the ``map`` query field for large
  networks.
