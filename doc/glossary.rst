========
Glossary
========

.. if you add new entries, keep the alphabetical sorting!

.. glossary::
  :sorted:

  ballooning
    A term describing dynamic changes to an instance's memory while the instance
    is running that don't require an instance reboot. Depending on the
    hypervisor and configuration, changes may be automatically initiated by the
    hypervisor (based on the memory usage of the node and instance), or may need
    to be initiated manually.

  BE parameter
    BE stands for *backend*. BE parameters are hypervisor-independent instance
    parameters, such as the amount of RAM/virtual CPUs allocated to an instance.

  DRBD
    A block device driver that can be used to build RAID1 across the network or
    across shared storage, while using only locally-attached storage.

  HV parameter
    HV stands for *hypervisor*. HV parameters describe the virtualization-
    specific aspects of the instance. For example, a HV parameter might describe
    what kernel (if any) to use to boot the instance or what emulation model to
    use for the emulated hard drives.

  HVM
    *Hardware Virtualization Mode*. In this mode, the virtual machine is
    oblivious to the fact that it is virtualized and all its hardware is
    emulated.

  LogicalUnit
    The code associated with an :term:`OpCode`; for example, the code that
    implements the startup of an instance.

  LUXI
     Local UniX Interface. The IPC method over :manpage:`unix(7)` sockets used
     between the CLI tools/RAPI daemon and the master daemon.

  OOB
    *Out of Band*. This term describes methods of accessing a machine (or parts
    of a machine) by means other than the usual network connection.  Examples
    include accessing a remote server via a physical serial console or via a
    virtual console. IPMI is also considered OOB access.

  OpCode
    A data structure encapsulating a basic cluster operation; for example: start
    instance, add instance, etc.

  PVM
    (Xen) *Para-virtualization mode*. In this mode, the virtual machine is aware
    that it is virtualized; therefore, there is no need for hardware emulation
    or virtualization.

  SoR
    *State of Record*. Refers to values/properties that come from an
    authoritative configuration source. For example, the maximum VCPU over-
    subscription ratio is a SoR value, but the current over-subscription ratio
    (based upon how many instances live on the node) is a :term:`SoW` value.

  SoW
    *State of the World*. Refers to values that directly describe the world, as
    opposed to values that come from the configuration (which are considered
    :term:`SoR`).

  tmem
    Xen Transcendent Memory (http://en.wikipedia.org/wiki/Transcendent_memory).
    tmem is a mechanism used by Xen to provide memory over-subscription.

  watcher
    :command:`ganeti-watcher` is a tool that should be run regularly from
    cron. The tool executes tasks such as restarting failed instances and
    restarting secondary DRBD devices. For more details, see the man page
    :manpage:`ganeti-watcher(8)`.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
