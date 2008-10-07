Ganeti 2.0 cluster parameters
=============================

.. contents::

Objective
---------

With the introduction of the HVM hypervisor in Ganeti 1.2 and the
implementation of multiple hypervisor support in Ganeti 2.0, the way
the cluster parameters are handled needs to be reorganized accordingly.

Background
----------

When the HVM hypervisor was introduced in Ganeti 1.2, the additional
instance parameters needed for it were simply added to the instance
namespace, as were additional parameters for the PVM hypervisor.

As a result of this, wether a particular parameter is valid for the
actual hypervisor could either be guessed from the name but only
really checked by following the code using it.

This design doc aims to provide an approach to solve this.

Overview
--------

The instance level hypervisor parameters will be moved into a separate
sub-tree of the instance name space. Also, a mechanismum to allow for
automatic checking and possibly validation of hypervisor parameters
will be outlined.


Detailed Design
---------------

Hypervisor Parameter
~~~~~~~~~~~~~~~~~~~~

A hypervisor parameter (or hypervisor specific parameter) is defined
as a parameter that is interpreted by the hypervisor support code in
Ganeti and usually is specific to a particular hypervisor (like the
kernel path for PVM which makes no sense for HVM or KVM).

Cluster parameters
~~~~~~~~~~~~~~~~~~

The cluster parameter namespace will be extended with cluster level
hypervisor specific parameters. The typical expected use case for this
is to store default values for instance level hypervisor parameters.


Instance parameters
~~~~~~~~~~~~~~~~~~~

The only hypervisor parameter to remain at the top level of the
instance namespace will be instance.hypervisor_type, specifying not
only the hypervisor type to be used for that instance, but also
implicitly the hypervisor type to use for parameter checks.

All other instance level hypervisor parameters will be moved into the
instance.hypervisor_params namespace subtree.

The names for hypervisor parameters in the instance.hypervisor_params
subtree should be choosen as generic as possible, especially if
specific parameters could conceivably be useful for more than one
hypervisor, e.g.
instance.hypervisor_params.vnc_console_port instead of using both
instance.hypervisor_params.hvm_vnc_console_port and
instance.hypervisor_params.kvm_vnc_console_port.

The instance.hypervisor_params subtree will be implemented as a dict.

Examples for instance level hypervisor parameters:

:boot_order: boot device order
:vnc_bind_address: bind address for VNC console
:vnc_bind_port: bind port for VNC console
:kernel_path: path to the kernel binary
:disk_type: type of the virtual disk interface

With this design, hypervisor specific parameters for disk and NIC
devices are defined globally for all devices of that type in the instance.
It may become necessary later to allow setting these parameters on a
per device basis, which will require design changes to the cluster
parameters.

All other, non hypervisor related parameters of the instance remain at
the top level of the instance namespace. This includes:

- disks
- nics
- mem
- vcpu
- status
- OS



Hypervisor support requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To support the new cluster parameter design, additional features will
be required from the hypervisor support implementations in Ganeti.

The hypervisor support  implementation API will be extended with the
following features:

:GetValidClusterParameters(): returns a list of valid cluster level
  parameters for this hypervisor,
:GetValidInstanceParameters(): provide a list of valid instance level
  parameters for this hypervisor,
:VerifyParameter(parameter_name, parameter_value): verifies the
  provided parameter against this hypervisor:

  - if the provided parameter name is valid for this hypervisor
  - if applicable, if the provided value is valid for this hypervisor

The VerifyParameter(..) function will return True or False.


The parameter validation will be used for every addition or change of
hypervisor parameters.
