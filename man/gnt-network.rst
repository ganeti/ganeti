gnt-network(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

gnt-network - Ganeti network administration

Synopsis
--------

**gnt-network** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-network** command is used for network definition administration
in the Ganeti system.

COMMANDS
--------

ADD
~~~

| **add**
| [--network=*NETWORK*]
| [--gateway=*GATEWAY*]
| [--add-reserved-ips=*RESERVEDIPS*]
| [--network6=*NETWORK6*]
| [--gateway6=*GATEWAY6*]
| [--mac-prefix=*MACPREFIX*]
| [--network-type=*NETWORKTYPE*]
| {*network*}

Creates a new network with the given name. The network will be unused
initially. To connect it to a node group, use ``gnt-network connect``.
``--network`` option is mandatory. All other are optional.

The ``--network`` option allows you to specify the network in a CIDR notation.

The ``--gateway`` option allows you to specify the default gateway for this
network.

The ``--network-type`` can be none, private or public.

IPv6 semantics can be assigned to the network via the ``--network6`` and
``--gateway6`` options. IP pool is meaningless for ipv6 so those two values
can be used for EUI64 generation from a NIC's mac value.

MODIFY
~~~~~~

| **modify**
| [--gateway=*GATEWAY*]
| [--add-reserved-ips=*RESERVEDIPS*]
| [--remove-reserved-ips=*RESERVEDIPS*]
| [--network6=*NETWORK6*]
| [--gateway6=*GATEWAY6*]
| [--mac-prefix=*MACPREFIX*]
| [--network-type=*NETWORKTYPE*]
| {*network*}

Modifies parameters from the network.

Unable to modify network (ip range). Create a new network if you want to do
so. All other options are documented in the **add** command above.

REMOVE
~~~~~~

| **remove** {*network*}

Deletes the indicated network, which must be not connected to any node group.

LIST
~~~~

| **list** [--no-headers] [--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [network...]

Lists all existing networks in the cluster.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti(7)**).

The ``-o`` option takes a comma-separated list of output fields.
If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

The available fields and their meaning are:

name
    the group name

group_count
    the number of nodegroups connected to the network

group_list
    the list of nodegroups connected to the network

inst_cnt
    the number of instances use the network

inst_list
    the list of instances that at least one of their NICs is assigned
    to the network

external_reservations
    the IPs that cannot be assigned to an instance

free_count
    how many IPs have left in the pool

gateway
    the networks gateway

map
    a nice text depiction of the available/reserved IPs in the network

reserved_count
    how many IPs have been reserved so far in the network

network6
    the ipv6 prefix of the network

gateway6
    the ipv6 gateway of the network

mac_prefix
    the mac_prefix of the network (if a NIC is assigned to the network it
    it gets the mac_prefix of the network)

network_type
    the type of the network (public, private)

If no group names are given, then all groups are included. Otherwise,
only the named groups will be listed.

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

List available fields for networks.

RENAME
~~~~~~

| **rename** {*oldname*} {*newname*}

Renames a given network from *oldname* to *newname*. NOT implemeted yet

INFO
~~~~

| **info** [network...]

Displays information about a given network.

CONNECT
~~~~~~~
| **connect** {*network*} {*group*} {*mode*} {*link*}

Connect a network to a given nodegroup with the netparams (*mode*, *link*).
Every nic will inherit those netparams if assigned in a network.
*group* can be ``all`` if you want to connect to all existing nodegroups

DISCONNECT
~~~~~~~~~~
| **disconnect** {*network*} {*group*}

Disconnect a network to a nodegroup. This is possible only if no instance
is using the network.
