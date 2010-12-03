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

| **add** {*group*}

Creates a new group with the given name. The node group will be
initially empty.

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

RENAME
~~~~~~

| **rename** {*oldname*} {*newname*}

Renames a given group from *oldname* to *newname*.
