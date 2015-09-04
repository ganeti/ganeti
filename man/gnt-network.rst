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

The **gnt-network** command is used for network definition and
administration in the Ganeti system. Each instance NIC can be connected
to a network via the ``network`` NIC parameter. See **gnt-instance**\(8)
for more details.

BUGS
----

The ``hail`` iallocator hasn't been updated to take networks into
account in Ganeti 2.7. The only way to guarantee that it works correctly
is having your networks connected to all nodegroups. This will be fixed
in a future version.

COMMANDS
--------

ADD
~~~

| **add**
| --network=*NETWORK*
| [\--gateway=*GATEWAY*]
| [\--add-reserved-ips=*RESERVEDIPS*]
| [\--network6=*NETWORK6*]
| [\--gateway6=*GATEWAY6*]
| [\--mac-prefix=*MACPREFIX*]
| [\--submit] [\--print-jobid]
| [\--no-conflicts-check]
| {*network*}

Creates a new network with the given name. The network will be unused
initially. To connect it to a node group, use ``gnt-network connect``.
``--network`` option is mandatory. All other are optional.

The ``--network`` option allows you to specify the network in a CIDR
notation.

The ``--gateway`` option allows you to specify the default gateway for
this network.

IPv6 semantics can be assigned to the network via the ``--network6`` and
``--gateway6`` options. IP pool is meaningless for IPV6 so those two
values can be used for EUI64 generation from a NIC's MAC address.

The ``--no-conflicts-check`` option can be used to skip the check for
conflicting IP addresses.

Note that a when connecting a network to a node group (see below) you
can specify also the NIC mode and link that will be used by instances on
that group to physically connect to this network. This allows the system
to work even if the parameters (eg. the VLAN number) change between
groups.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

MODIFY
~~~~~~

| **modify**
| [\--gateway=*GATEWAY*]
| [\--add-reserved-ips=*RESERVEDIPS*]
| [\--remove-reserved-ips=*RESERVEDIPS*]
| [\--network6=*NETWORK6*]
| [\--gateway6=*GATEWAY6*]
| [\--mac-prefix=*MACPREFIX*]
| [\--submit] [\--print-jobid]
| {*network*}

Modifies parameters from the network.

Unable to modify network (IP address range). Create a new network if you
want to do so. All other options are documented in the **add** command
above.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

REMOVE
~~~~~~

| **remove** [\--submit] [\--print-jobid] {*network*}

Deletes the indicated network, which must be not connected to any node group.

See **ganeti**\(7) for a description of ``--submit`` and other common options.

LIST
~~~~

| **list** [\--no-headers] [\--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [network...]

Lists all existing networks in the cluster. If no group names are given,
then all groups are included. Otherwise, only the named groups will be
listed.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be used
between the output fields. Both these options are to help scripting.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti**\(7)).

The ``-o`` option takes a comma-separated list of output fields. If the
value of the option starts with the character ``+``, the new fields will
be added to the default list. This allows to quickly see the default
list plus a few other fields, instead of retyping the entire list of
fields.

The available fields and their meaning are:

@QUERY_FIELDS_NETWORK@

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

List available fields for networks.

INFO
~~~~

| **info** [network...]

Displays information about a given network.

CONNECT
~~~~~~~

| **connect**
| [\--no-conflicts-check]
| [{-N|\--nic-parameters} *nic-param*=*value*[,*nic-param*=*value*...]]
| {*network*} [*groups*...]

Connect a network to given node groups (all if not specified) with the
network parameters defined via the ``--nic-parameters`` option. Every
network interface will inherit those parameters if assigned to a network.

The ``--no-conflicts-check`` option can be used to skip the check for
conflicting IP addresses.

Passing *mode* and *link* as possitional arguments along with
*network* and *groups* is deprecated and not supported any more.

DISCONNECT
~~~~~~~~~~

| **disconnect** {*network*} [*groups*...]

Disconnect a network from given node groups (all if not specified). This
is possible only if no instance is using the network.


Tags
~~~~

ADD-TAGS
^^^^^^^^

**add-tags** [\--from *file*] {*networkname*} {*tag*...}

Add tags to the given network. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be extended
with the contents of that file (each line becomes a tag). In this case,
there is not need to pass tags on the command line (if you do, both
sources will be used). A file name of ``-`` will be interpreted as
stdin.

LIST-TAGS
^^^^^^^^^

**list-tags** {*networkname*}

List the tags of the given network.

REMOVE-TAGS
^^^^^^^^^^^

**remove-tags** [\--from *file*] {*networkname*} {*tag*...}

Remove tags from the given network. If any of the tags are not existing
on the network, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag). In
this case, there is not need to pass tags on the command line (if you
do, tags from both sources will be removed). A file name of ``-`` will
be interpreted as stdin.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
