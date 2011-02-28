========
Glossary
========

.. if you add new entries, keep the alphabetical sorting!

.. glossary::

  BE Parameter
    BE stands for Backend. BE parameters are hypervisor-independent
    instance parameters such as the amount of RAM/virtual CPUs it has
    been allocated.

  HVM
    Hardware virtualization mode, where the virtual machine is
    oblivious to the fact that's being virtualized and all the
    hardware is emulated.

  LogicalUnit
    The code associated with an OpCode, e.g. the code that implements
    the startup of an instance.

  LUXI
     Local UniX Interface. The IPC method over unix sockets used between
     the cli tools and the master daemon.

  OpCode
    A data structure encapsulating a basic cluster operation; for
    example, start instance, add instance, etc.

  PVM
    Para-virtualization mode, where the virtual machine knows it's being
    virtualized and as such there is no need for hardware emulation.

  watcher
    ``ganeti-watcher`` is a tool that should be run regularly from cron
    and takes care of restarting failed instances, restarting secondary
    DRBD devices, etc. For more details, see the man page
    :manpage:`ganeti-watcher(8)`.

.. vim: set textwidth=72 :
