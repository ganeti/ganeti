gnt-group(8) Ganeti | Version @GANETI_VERSION@
==============================================

Name
----

gnt-group - Ganeti node-group administration

Synopsis
--------

**gnt-group** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-group** command is used for node group administration in
the Ganeti system.

COMMANDS
--------

ADD
~~~

| **add**
| [--node-parameters=*NDPARAMS*]
| [--alloc-policy=*POLICY*]
| {*group*}

Creates a new group with the given name. The node group will be
initially empty; to add nodes to it, use ``gnt-group assign-nodes``.

The ``--node-parameters`` option allows you to set default node
parameters for nodes in the group. Please see **ganeti**(7) for more
information about supported key=value pairs.

The ``--alloc-policy`` option allows you to set an allocation policy for
the group at creation time. Possible values are:

unallocable
    nodes in the group should not be candidates for instance allocation,
    and the operation (e.g., instance creation) should fail if only
    groups in this state could be found to satisfy the requirements.

last_resort
    nodes in the group should not be used for instance allocations,
    unless this would be the only way to have the operation succeed.

preferred
    nodes in the group can be used freely for allocation of instances
    (this is the default). Note that prioritization among groups in this
    state will be deferred to the iallocator plugin that's being used.

ASSIGN-NODES
~~~~~~~~~~~~

| **assign-nodes**
| [--force]
| {*group*} {*node*...}

Assigns one or more nodes to the specified group, moving them from their
original group (or groups).

By default, this command will refuse to proceed if the move would split
between groups any instance that was not previously split (a split
instance is an instance with a mirrored disk template, e.g. DRBD, that
has the primary and secondary nodes in different node groups). You can
force the operation with ``--force``.

MODIFY
~~~~~~

| **modify**
| [--node-parameters=*NDPARAMS*]
| [--alloc-policy=*POLICY*]
| {*group*}

Modifies some parameters from the node group.

The ``--node-parameters`` and ``--alloc-policy`` optiosn are documented
in the **add** command above.

REMOVE
~~~~~~

| **remove** {*group*}

Deletes the indicated node group, which must be empty.

LIST
~~~~

| **list** [--no-headers] [--separator=*SEPARATOR*]
| [-o *[+]FIELD,...*] [group...]

Lists all existing node groups in the cluster.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-o`` option takes a comma-separated list of output fields.
If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

The available fields and their meaning are:

name
    the group name

uuid
    the group's UUID

node_cnt
    the number of nodes in the node group

node_list
    the list of nodes that belong to this group

pinst_cnt
    the number of primary instances in the group (i.e., the number of
    primary instances nodes in this group have)

pinst_list
    the list of primary instances in the group

alloc_policy
    the current allocation policy for the group

ctime
    the creation time of the group; note that this field contains spaces
    and as such it's harder to parse

    if this attribute is not present (e.g. when upgrading from older
    versions), then "N/A" will be shown instead

mtime
    the last modification time of the group; note that this field
    contains spaces and as such it's harder to parse

serial_no
    the so called 'serial number' of the group; this is a numeric field
    that is incremented each time the node is modified, and it can be
    used to detect modifications

If no group names are given, then all groups are included. Otherwise,
only the named groups will be listed.

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

List available fields for node groups.

RENAME
~~~~~~

| **rename** {*oldname*} {*newname*}

Renames a given group from *oldname* to *newname*.
