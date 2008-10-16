Ganeti 2.0 cluster parameters
=============================

.. contents::

Objective
---------

We need to enhance the way attributes for instances and other clusters
parameters are handled internally within Ganeti in order to have
better flexibility in the following cases:

- introducting new parameters
- writing command line interfaces or APIs for these parameters
- supporting new 2.0 features

Background
----------

When the HVM hypervisor was introduced in Ganeti 1.2, the additional
instance parameters needed for it were simply added to the instance
namespace, as were additional parameters for the PVM hypervisor.

As a result of this, wether a particular parameter is valid for the
actual hypervisor could either be guessed from the name but only
really checked by following the code using it. Similar to this case,
other parameters are not valid in all cases, and were simply added to
the top-level instance objects.

Overview
--------

Across all cluster configuration data, we have multiple classes of
parameters:

A. cluster-wide parameters (e.g. name of the cluster, the master);
   these are the ones that we have today, and are unchanged from the
   current model

#. node parameters

#. instance specific parameters, e.g. the name of disks (LV), that
   cannot be shared with other instances

#. instance parameters, that are or can be the same for many
   instances, but are not hypervisor related; e.g. the number of VCPUs,
   or the size of memory

#. instance parameters that are hypervisor specific (e.g. kernel_path
   or PAE mode)



Detailed Design
---------------

The following definitions for instance parameters will be used below:

hypervisor parameter
  a hypervisor parameter (or hypervisor specific parameter) is defined
  as a parameter that is interpreted by the hypervisor support code in
  Ganeti and usually is specific to a particular hypervisor (like the
  kernel path for PVM which makes no sense for HVM).

backend parameter
  a backend parameter is defined as an instance parameter that can be
  shared among a list of instances, and is either generic enough not
  to be tied to a given hypervisor or cannot influence at all the
  hypervisor behaviour.

  For example: memory, vcpus, auto_balance

  All these parameters will be encoded into constants.py with the prefix "BE\_"
  and the whole list of parameters will exist in the set "BES_PARAMETERS"

proper parameter
  a parameter whose value is unique to the instance (e.g. the name of a LV,
  or the MAC of a NIC)

As a general rule, for all kind of parameters, “None” (or in
JSON-speak, “nil”) will no longer be a valid value for a parameter. As
such, only non-default parameters will be saved as part of objects in
the serialization step, reducing the size of the serialized format.

Cluster parameters
~~~~~~~~~~~~~~~~~~

Cluster parameters remain as today, attributes at the top level of the
Cluster object. In addition, two new attributes at this level will
hold defaults for the instances:

- hvparams, a dictionary indexed by hypervisor type, holding default
  values for hypervisor parameters that are not defined/overrided by
  the instances of this hypervisor type

- beparams, a dictionary holding (for 2.0) a single element 'default',
  which holds the default value for backend parameters

Node parameters
~~~~~~~~~~~~~~~

Node-related parameters are very few, and we will continue using the
same model for these as previously (attributes on the Node object).

Instance parameters
~~~~~~~~~~~~~~~~~~~

As described before, the instance parameters are split in three:
instance proper parameters, unique to each instance, instance
hypervisor parameters and instance backend parameters.

The “hvparams” and “beparams” are kept in two dictionaries at instance
level. Only non-default parameters are stored (but once customized, a
parameter will be kept, even with the same value as the default one,
until reset).

The names for hypervisor parameters in the instance.hvparams subtree
should be choosen as generic as possible, especially if specific
parameters could conceivably be useful for more than one hypervisor,
e.g. instance.hvparams.vnc_console_port instead of using both
instance.hvparams.hvm_vnc_console_port and
instance.hvparams.kvm_vnc_console_port.

There are some special cases related to disks and NICs (for example):
a disk has both ganeti-related parameters (e.g. the name of the LV)
and hypervisor-related parameters (how the disk is presented to/named
in the instance). The former parameters remain as proper-instance
parameters, while the latter value are migrated to the hvparams
structure. In 2.0, we will have only globally-per-instance such
hypervisor parameters, and not per-disk ones (e.g. all NICs will be
exported as of the same type).

Starting from the 1.2 list of instance parameters, here is how they
will be mapped to the three classes of parameters:

- name (P)
- primary_node (P)
- os (P)
- hypervisor (P)
- status (P)
- memory (BE)
- vcpus (BE)
- nics (P)
- disks (P)
- disk_template (P)
- network_port (P)
- kernel_path (HV)
- initrd_path (HV)
- hvm_boot_order (HV)
- hvm_acpi (HV)
- hvm_pae (HV)
- hvm_cdrom_image_path (HV)
- hvm_nic_type (HV)
- hvm_disk_type (HV)
- vnc_bind_address (HV)
- serial_no (P)


Parameter validation
~~~~~~~~~~~~~~~~~~~~

To support the new cluster parameter design, additional features will
be required from the hypervisor support implementations in Ganeti.

The hypervisor support  implementation API will be extended with the
following features:

:PARAMETERS: class-level attribute holding the list of valid parameters
  for this hypervisor
:CheckParamSyntax(hvparams): checks that the given parameters are
  valid (as in the names are valid) for this hypervisor; usually just
  comparing hvparams.keys() and cls.PARAMETERS; this is a class method
  that can be called from within master code (i.e. cmdlib) and should
  be safe to do so
:ValidateParameters(hvparams): verifies the values of the provided
  parameters against this hypervisor; this is a method that will be
  called on the target node, from backend.py code, and as such can
  make node-specific checks (e.g. kernel_path checking)

Default value application
~~~~~~~~~~~~~~~~~~~~~~~~~

The application of defaults to an instance is done in the Cluster
object, via two new methods as follows:

- ``Cluster.FillHV(instance)``, returns 'filled' hvparams dict, based on
  instance's hvparams and cluster's ``hvparams[instance.hypervisor]``

- ``Cluster.FillBE(instance, be_type="default")``, which returns the
  beparams dict, based on the instance and cluster beparams

The FillHV/BE transformations will be used, for example, in the RpcRunner
when sending an instance for activation/stop, and the sent instance
hvparams/beparams will have the final value (noded code doesn't know
about defaults).

LU code will need to self-call the transformation, if needed.

Opcode changes
~~~~~~~~~~~~~~

The parameter changes will have impact on the OpCodes, especially on
the following ones:

- OpCreateInstance, where the new hv and be parameters will be sent as
  dictionaries; note that all hv and be parameters are now optional, as
  the values can be instead taken from the cluster
- OpQueryInstances, where we have to be able to query these new
  parameters; the syntax for names will be ``hvparam/$NAME`` and
  ``beparam/$NAME`` for querying an individual parameter out of one
  dictionary, and ``hvparams``, respectively ``beparams``, for the whole
  dictionaries
- OpModifyInstance, where the the modified parameters are sent as
  dictionaries

Additionally, we will need new OpCodes to modify the cluster-level
defaults for the be/hv sets of parameters.

Caveats
-------

One problem that might appear is that our classification is not
complete or not good enough, and we'll need to change this model. As
the last resort, we will need to rollback and keep 1.2 style.

Another problem is that classification of one parameter is unclear
(e.g. ``network_port``, is this BE or HV?); in this case we'll take
the risk of having to move parameters later between classes.

Security
--------

The only security issue that we foresee is if some new parameters will
have sensitive value. If so, we will need to have a way to export the
config data while purging the sensitive value.

E.g. for the drbd shared secrets, we could export these with the
values replaced by an empty string.
