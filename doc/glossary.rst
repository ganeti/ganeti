========
Glossary
========

.. if you add new entries, keep the alphabetical sorting!

.. glossary::
  :sorted:

  ballooning
    A term describing runtime, dynamic changes to an instance's memory,
    without having to reboot the instance. Depending on the hypervisor
    and configuration, the changes need to be initiated manually, or
    they can be automatically initiated by the hypervisor based on the
    node and instances memory usage.

  BE parameter
    BE stands for *backend*. BE parameters are hypervisor-independent
    instance parameters such as the amount of RAM/virtual CPUs it has
    been allocated.

  DRBD
    A block device driver that can be used to build RAID1 across the
    network or even shared storage, while using only locally-attached
    storage.

  HV parameter
    HV stands for *hypervisor*. HV parameters are the ones that describe
    the virtualization-specific aspects of the instance; for example,
    what kernel to use to boot the instance (if any), or what emulation
    model to use for the emulated hard drives.

  HVM
    Hardware virtualization mode, where the virtual machine is oblivious
    to the fact that's being virtualized and all the hardware is
    emulated.

  LogicalUnit
    The code associated with an :term:`OpCode`, e.g. the code that
    implements the startup of an instance.

  LUXI
     Local UniX Interface. The IPC method over :manpage:`unix(7)`
     sockets used between the CLI tools/RAPI daemon and the master
     daemon.

  OOB
    *Out of Band*. This term describes methods of accessing a machine
    (or parts of a machine) not via the usual network connection. For
    example, accessing a remote server via a physical serial console or
    via a virtual one IPMI counts as out of band access.

  OpCode
    A data structure encapsulating a basic cluster operation; for
    example, start instance, add instance, etc.

  PVM
    (Xen) Para-virtualization mode, where the virtual machine knows it's
    being virtualized and as such there is no need for hardware
    emulation or virtualization.

  SoR
    *State of Record*. Refers to values/properties that come from an
    authoritative configuration source. For example, the maximum VCPU
    over-subscription ratio is a *SoR* value, but the current
    over-subscription ration (based on how many instances live on the
    node) is a :term:`SoW` value.

  SoW
    *State of the World*. Refers to values that describe directly the
    world, as opposed to values that come from the
    configuration. Contrast with :term:`SoR`.

  tmem
    Xen Transcendent Memory
    (http://en.wikipedia.org/wiki/Transcendent_memory). It is a
    mechanism used by Xen to provide memory over-subscription.

  watcher
    :command:`ganeti-watcher` is a tool that should be run regularly
    from cron and takes care of restarting failed instances, restarting
    secondary DRBD devices, etc. For more details, see the man page
    :manpage:`ganeti-watcher(8)`.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
