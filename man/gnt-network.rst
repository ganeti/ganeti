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
| [--submit]
| {*network*}

Creates a new network with the given name. The network will be unused
initially. To connect it to a node group, use ``gnt-network connect``.
``--network`` option is mandatory. All other are optional.

The ``--network`` option allows you to specify the network in a CIDR notation.

The ``--gateway`` option allows you to specify the default gateway for this
network.

The ``--network-type`` can be none, private or public.

IPv6 semantics can be assigned to the network via the ``--network6`` and
``--gateway6`` options. IP pool is meaningless for IPV6 so those two values
can be used for EUI64 generation from a NIC's MAC address.

See **ganeti(7)** for a description of ``--submit`` and other common options.

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
| [--submit]
| {*network*}

Modifies parameters from the network.

Unable to modify network (IP address range). Create a new network if you want
to do so. All other options are documented in the **add** command above.

See **ganeti(7)** for a description of ``--submit`` and other common options.

REMOVE
~~~~~~

| **remove** [--submit] {*network*}

Deletes the indicated network, which must be not connected to any node group.

See **ganeti(7)** for a description of ``--submit`` and other common options.

LIST
~~~~

| **list** [--no-headers] [--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [network...]

Lists all existing networks in the cluster. If no group names are given, then
all groups are included. Otherwise, only the named groups will be listed.

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

@QUERY_FIELDS_NETWORK@

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

List available fields for networks.

RENAME
~~~~~~

| **rename** {*oldname*} {*newname*}

Renames a given network from *oldname* to *newname*. NOT implemeted yet

TAGS
~~~

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

Remove tags from the given network. If any of the tags are not
existing on the network, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag). In
this case, there is not need to pass tags on the command line (if you
do, tags from both sources will be removed). A file name of ``-`` will
be interpreted as stdin.


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
