=============
OVF converter
=============

Using ``ovfconverter`` from the ``tools`` directory, one can easily
convert previously exported Ganeti instance into OVF package, supported
by VMWare, VirtualBox and some other virtualization software. It is
also possible to use instance exported from such a tool and convert it
to Ganeti config file, used by ``gnt-backup import`` command.

For the internal design of the converter and more detailed description,
including listing of available command line options, please refer to
:doc:`design-ovf-support`

As the amount of Ganeti-specific details, that need to be provided in
order to import an external instance, is rather large, we will present
here some examples of importing instances from different sources.
It is also worth noting that there are some limitations regarding
support for different hardware.

Limitations on import
=====================

Network
-------
Available modes for the network include ``bridged`` and ``routed``.
There is no ``NIC`` mode, which is typically used e.g. by VirtualBox.
For most usecases this should not be of any effect, since if
``NetworkSection`` contains any networks which are not discovered as
``bridged`` or ``routed``, the network mode is assigned automatically,
using Ganeti's cluster defaults.

Backend
-------
The only values that are taken into account regarding Virtual Hardware
(described in ``VirtualHardwareSection`` of the ``.ovf`` file) are:

- number of virtual CPUs
- RAM memory
- hard disks
- networks

Neither USB nor CD-ROM drive are used in Ganeti. We decided to simply
ignore unused elements of this section, so their presence won't raise
any warnings.


Operating System
----------------
List of operating systems available on a cluster is viewable using
``gnt-os list`` command. When importing from external source, providing
OS type in a command line (``--os-type=...``) is **required**. This is
because rven if the type is given in OVF description, it is not detailed
enough for Ganeti to know which os-specific scripts to use.


Import examples
===============

Ganeti's OVF
------------
If you are importing instance created using ``ovfconverter export`` --
you most probably will not have to provide any additional information.
In that case, the following is all you need (unless you wish to change
some configuration options)::

	ovfconverter import ganeti.ovf
	[...]
	gnt-instance import -n <node> <instance name>


Virtualbox, VMWare and other external sources
---------------------------------------------
In case of importing from external source, you will most likely have to
provide the following details:

- ``os-type`` can be any operating system listed on ``gnt-os list``
- ``name`` that has to be resolvable, as it will be used as instance
  name (even if your external instance has a name, it most probably is
  not resolvable to an IP address)

These are not the only options, but the recommended ones. For the
complete list of available options please refer to
`Command Line description <design-ovf-support.rst>`

Minimalistic but complete example of importing Virtualbox's OVF
instance may look like::

    ovfconverter virtualbox.ovf --os-type=lenny-image \
      --name=xen.test.i1 --disk-template=diskless
    [...]
    gnt-instance import -n node1.xen xen.test.i1



Export example
==============

Exporting instance into ``.ovf`` format is pretty streightforward and
requires little - if any - explanation. The only compulsory detail is
the required disk format, provided using the ``--format`` option.

Export to another Ganeti instance
---------------------------------
If for some reason it is convenient for you to use ``ovfconverter`` to
move instance between clusters (e.g. because of the disk compression),
the complete example of export may look like this::

    gnt-backup export -n node1.xen xen.test.i1
    [...]
    ovfconverter export --format=vmdk --ova \
      /srv/ganeti/export/xen.i1.node1.xen/config.ini
    [...]

The result is then in
``/srv/ganeti/export/xen.i1.node1.xen/xen.test.i1.ova``

Export to Virtualbox/VMWare/other external tool
-----------------------------------------------
Typically, when exporting to external tool we do not want
Ganeti-specific configuration to be saved. In that case, simply use the
``--external`` option::

    gnt-backup export -n node1.xen xen.test.i1
    [...]
    ovfconverter export --external --output-dir ~/ganeti-instance/ \
      /srv/ganeti/export/xen.i1.node1.xen/config.ini


Known issues
============

Export
------
When exporting to **VirtualBox**, you may encounter errors regarding
network. If that is the case, simply change the network type in options
to ``NAT``.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
