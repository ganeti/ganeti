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
| [{-D|--disk-parameters} *disk-template*:*disk-param*=*value*[,*disk-param*=*value*...]]
| [--specs-cpu-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-mem-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-nic-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-templates *template* [,*template*...]]
| [--disk-state *diskstate*]
| [--hypervisor-state *hvstate*]
| {*group*}

Creates a new group with the given name. The node group will be
initially empty; to add nodes to it, use ``gnt-group assign-nodes``.

The ``--node-parameters`` option allows you to set default node
parameters for nodes in the group. Please see **ganeti**(7) for more
information about supported key=value pairs and their corresponding
options.

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

The ``-D (--disk-parameters)`` option allows you to set the disk
parameters for the node group; please see the section about
**gnt-cluster add** in **gnt-cluster**(8) for more information about
disk parameters

The ``--specs-...`` options specify instance policies on the node group,
and are documented in the **gnt-cluster**(8) man page.

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
| [--hypervisor-state *hvstate*]
| [{-D|--disk-parameters} *disk-template*:*disk-param*=*value*[,*disk-param*=*value*...]]
| [--disk-state *diskstate*]
| [--specs-cpu-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-mem-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-nic-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [--specs-disk-templates *template* [,*template*...]]
| {*group*}

Modifies some parameters from the node group.

The ``--node-parameters`` and ``--alloc-policy`` options are documented
in the **add** command above. ``--hypervisor-state`` as well as
``--disk-state`` are documented in detail in **ganeti**(7).

The ``--node-parameters``, ``--alloc-policy``, ``-D
(--disk-parameters)`` options are documented in the **add** command
above.

The ``--specs-...`` options specify instance policies on the node group,
and are documented in the **gnt-cluster**(8) man page.

REMOVE
~~~~~~

| **remove** {*group*}

Deletes the indicated node group, which must be empty. There must always be at
least one group, so the last group cannot be removed.

LIST
~~~~

| **list** [--no-headers] [--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [--filter] [group...]

Lists all existing node groups in the cluster.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti(7)**).

The ``-o`` option takes a comma-separated list of output fields.
If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

The available fields and their meaning are:

@QUERY_FIELDS_GROUP@

If exactly one argument is given and it appears to be a query filter
(see **ganeti(7)**), the query result is filtered accordingly. For
ambiguous cases (e.g. a single field name as a filter) the ``--filter``
(``-F``) option forces the argument to be treated as a filter.

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


EVACUATE
~~~~~~~~

**evacuate** [--iallocator *NAME*] [--to *GROUP*...] {*group*}

This command will move all instances out of the given node group.
Instances are placed in a new group by an iallocator, either given on
the command line or as a cluster default.

If no specific destination groups are specified using ``--to``, all
groups except the evacuated group are considered.

Example::

    # gnt-group evacuate -I hail --to rack4 rack1


TAGS
~~~~

ADD-TAGS
^^^^^^^^

**add-tags** [--from *file*] {*groupname*} {*tag*...}

Add tags to the given node group. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be extended
with the contents of that file (each line becomes a tag). In this case,
there is not need to pass tags on the command line (if you do, both
sources will be used). A file name of ``-`` will be interpreted as
stdin.

LIST-TAGS
^^^^^^^^^

**list-tags** {*groupname*}

List the tags of the given node group.

REMOVE-TAGS
^^^^^^^^^^^

**remove-tags** [--from *file*] {*groupname*} {*tag*...}

Remove tags from the given node group. If any of the tags are not
existing on the node, the entire operation will abort.

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
