=====================
Instance Reservations
=====================

.. contents:: :depth: 4

This is a design document detailing the addition of a concept
of reservations for forthcoming instances to Ganeti.


Current state and shortcomings
==============================

Currently, for a new instance, all information about the instance,
including a resolvable full name, needs to be present before an
instance creation can be attempted. Moreover, the only way to find
out if a cluster can host an instance is to try creating it. This
can lead to problems in situations where the host name can only
be determined, and hence DNS entries created, once the cluster for
the instance is chosen. If lot of instances are created in parallel,
by the time the DNS entries propagated, the cluster capacity might
already be exceeded.


Proposed changes
================

The proposed solution to overcome this shortcoming is to support
*forthcoming instances*. Those forthcoming instances only exist as entries in
in the configuration, hence creation and removal is cheap. Forthcoming instances
can have an arbitrary subset of the attributes of a real instance with
only the UUID being mandatory. In a similar way, their disks are also
considered forthcoming. If a forthcoming instance specifies resources
(memory, disk sizes, number of CPUs), these resources are accounted
for as if they were real. In particular, a forthcoming can always be
turned into a real one without running out of resources.

RAPI extension
--------------

To accomdate the handling of forthcoming instances, the :doc:`rapi`
will be extended as follows.

The following functionality will be added to existing resources.

- /2/instances/

  - POST. This request will have an additional, optional, ``forthcoming``
    flag with default ``False``. If the ``forthcoming`` flag is set, all
    parameters are optional, including the instance name. Even if
    ``forthcoming`` is set, the result of this request will still be the job id
    to be used later for polling. A job to create a forthcoming instance,
    however, will return the UUID of the instance instead of the hosts
    allocated for it.

- /2/instances/[instance_name]/modify

  - PUT. This request will be able to handle forthcoming instances
    in the same way as existing ones.

The following resources will be added.

- /2/instances/[instance_uuid]/modify

  - PUT. This will behave the same as the ``modify`` indexed by instance
    name and is added to allow modification of an instance that does
    not yet have a name.

- /2/instances/[instance_uuid]/rename

  - PUT. This will behave the same as the ``rename`` indexed by
    instance name. This will allow to assign a name to a forthcoming
    instance.

- /2/instances/[instance_name]/create

  - POST. Create the forthcoming instance. It is a prerequisite that
    all mandatory parameters of the instance are specified by now.
    It will return the id of the creation job, for later polling.


Representation in the Configuration
-----------------------------------

As for most part of the system, forthcoming instances and their disks are to
be treated as if they were real. Therefore, the wire representation will
be by adding an additional, optional, ``fortcoming`` flag to the ``instances``
and ``disks`` objects. Additionally, the internal consistency condition will
be relaxed to have all non-uuid fields optional if an instance or disk is
forthcoming.

Rationale
~~~~~~~~~

The alternative to the chosen approach would be to add a new top-level object
``forthcoming_instances`` to the configuration. Both approaches bear the risk
of introducing subtle bugs. Adding a new top-level object bears the risk of
missing in some places to take into account the resources consumed by the
forthcoming instances. Adding a new attribute and relaxing the consistency
conditions bears the risk that some parts of the Python code cannot handle the
fact that some fields are now optional if the instance is forthcoming.
The design choice is to prefer the latter kind of errors, as they will always
show up immediately when a faulty part of the code is touched and will always
precisely indicate the part of the code base that needs to be changed.

Haskell Representation
~~~~~~~~~~~~~~~~~~~~~~

The semantical condition on the instance fields renders the type into
a Pascal-style variant record (one element of an enumeration type,
and the remaining fields depend on the value of that field). Of course, in
the Haskell part of our code base, this will be represented in the standard way
having two constructors for the type; additionally there will be accessors
for all the fields of the JSON representation (yielding ``Maybe`` values,
as they can be optional if we're in the ``Forthcoming`` constuctor).


Adaptions of htools
-------------------

Forthcoming instances are handled by htools essentially the same way as
real instances with more possible moves, as a forthcoming instance may
change primary and secondary node simultaneously. The restriction of not
changing node group without explicit user request to do so remains.
Wherever possible, moves of forthcoming instances are preferred over
moving real instances, as forthcoming instances can be moved for
free. Implementation wise, the existing ``Instance`` data structure is
used, and a new bit ``forthcoming`` is added; for forthcoming
instances, the ``name`` field will carry the UUID.
