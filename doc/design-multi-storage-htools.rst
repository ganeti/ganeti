==================================================
HTools support for multiple storage units per node
==================================================

.. contents:: :depth: 4

This design document describes changes to hbal and related components (first
and foremost LUXI), that will allow it to handle nodes that can't be considered
monolithic in regard to disk layout, for example because they have multiple
different storage units available.

Current state and shortcomings
==============================

Currently the htools assume that there is one storage unit per node and that it can
be arbitrarily split among instances. This leads to problems in clusters
where multiple storage units are present: There might be 10GB DRBD and 10GB
plain storage available on a node, for a total of 20GB. If an instance that
uses 15GB of a single type of storage is requested, it can't actually fit on
the node, but the current implementation of hail doesn't notice this.

This behaviour is clearly wrong, but the problem doesn't arise often in current
setup, due to the fact that instances currently only have a single
storage type and that users typically use node groups to differentiate between
different node storage layouts.

For the node show action, RAPI only returns

* ``dfree``: The total amount of free disk space
* ``dtotal``: The total amount of disk space

which is insufficient for the same reasons.


Proposed changes
================

Definitions
-----------

* All disks have exactly one *desired storage unit*, which determines where and
  how the disk can be stored. If the disk is transfered, the desired storage
  unit remains unchanged. The desired storage unit includes specifics like the
  volume group in the case of LVM based storage.
* A *storage unit* is a specific storage location on a specific node. Storage
  units have exactly one desired storage unit they can contain. A storage unit
  further has an identifier (containing the storage type, a key and possibly
  parameters), a total capacity, and a free capacity. A node cannot
  contain multiple storage units of the same desired storage unit.
* For the purposes of this document a *disk* has a desired storage unit and a size.
* A *disk can be moved* to a node, if there is at least one storage unit on
  that node which can contain the desired storage unit of the disk and if the
  free capacity is at least the size of the disk.
* An *instance can be moved* to a node, if all its disks can be moved there
  one-by-one.

LUXI and IAllocator protocol extension
--------------------------------------

The LUXI and IAllocator protocols are extended to include in the ``node``:

* ``storage``: a list of objects (storage units) with
  #. Storage unit, containing in order:

     #. storage type
     #. storage key (e.g. volume group name)
     #. extra parameters (e.g. flag for exclusive storage) as a list.

  #. Amount free in MiB
  #. Amount total in MiB

.. code-block:: javascript

    {
      "storage": [
        { "sunit": ["drbd8", "xenvg", []]
        , "free": 2000,
        , "total": 4000
        },
        { "sunit": ["file", "/path/to/storage1", []]
        , "free": 5000,
        , "total": 10000
        },
        { "sunit": ["file", "/path/to/storage2", []]
        , "free": 1000,
        , "total": 20000
        },
        { "sunit": ["lvm-vg", "xenssdvg", [false]]
        , "free": 1024,
        , "total": 1024
        }
      ]
    }

is a node with an LVM volume group mirrored over DRBD, two file storage
directories, one half full, one mostly full, and a non-mirrored volume group.

The storage type ``drbd8`` needs to be added in order to differentiate between
mirrored storage and non-mirrored storage.
The storage key signals the volume group used and the storage unit takes no
additional parameters.

Text protocol extension
-----------------------

The same field is optionally present in the HTools text protocol:

* a new "storage" column is added to the node section, which is a semicolon
  separated list of comma separated fields in the order
  #. ``free``
  #. ``total``
  #. ``sunit``, which in itself contains

     #. the storage type
     #. the storage key
     #. extra arguments

For example:

    2000,4000,drbd,xenvg;5000,10000,file,/path/to/storage1;1000,20000;
    [...]

Interpretation
--------------

``hbal`` and ``hail`` will use this information only if available, if the data
file doesn't contain the ``storage`` field the old algorithm is used.

If the node information contains the ``storage`` field, hbal and hail will
assume that only the space compatible with the disk's requirements is
available. For an instance to fit a node, all it's disks need to fit there
separately. For a disk to fit a node, a storage unit of the type of
the disk needs to have enough free space to contain it. The total free storage
is not taken into consideration.

Ignoring the old information will in theory introduce a backwards
incompatibility: If the total free storage is smaller than to the sum of the
free storage reported in the ``storage`` field a previously illegal move will
become legal.

Balancing
---------

In order to determine a storage location for an instance, we collect analogous
metrics to the current total node free space metric -- namely the standard deviation
statistic of the free space per storage unit.

The *standard deviation metric* of a desired storage unit is the sample standard
deviation of the percentage of free space of storage units compatible.

The *full storage metric* is a average of the standard deviation metrics of the
desired storage units.

This is backwards compatible in-so-far as that

#. For a single storage unit per node it will have the same value.
#. The weight of the storage versus the other metrics remains unchanged.

Further this retains the property that scarce resources with low total will
tend to have bigger impact on the metric than those with large totals, because
in latter case the relative differences will not make for a large standard
deviation.

Ignoring nodes that do not contain the desired storage unit additionally
boosts the importance of the scarce desired storage units, because having more
storage units of a desired storage unit will tend to make the standard
deviation metric smaller.
