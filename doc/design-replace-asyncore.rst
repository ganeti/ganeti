=======================================================
Replace Usage Of asyncore With Lightweight Alternatives
=======================================================

:Created: 2026-02-04
:Status: Draft

.. contents:: :depth: 4

This is a design document detailing how to remove the deprecated
Python asyncore module from the Ganeti codebase and replace it
with lightweight alternatives.


Current state and shortcomings
------------------------------

The asyncore module was deprecated in Python 3.6 and removed entirely in
Python 3.12, making Ganeti incompatible with modern Python versions. Ganeti
currently relies on asyncore in the following areas:

- HTTP server implementation (lib/http/server.py)
- daemon event loop (lib/daemon.py: ``Mainloop`` class)
- signal notification mechanism (lib/daemon.py: ``AsyncAwaker`` class)
- inotify file watcher (lib/asyncnotifier.py: ``AsyncNotifier`` class)
- UDP client socket (lib/daemon.py: ``AsyncUDPSocket`` class, used by
  ``ConfdAsyncUDPClient``)

The HTTP server migration to a threaded implementation will significantly
reduce the scope of remaining asyncore dependencies, as the HTTP server will
operate independently of the asyncore event loop.

While asyncio would be the canonical replacement for asyncore, it introduces
unnecessary complexity for Ganeti's use cases:

- Requires extensive restructuring (``async``/``await`` throughout the codebase)
- Adds cognitive overhead for contributors unfamiliar with async patterns
- Provides no meaningful benefit for Ganeti's workload characteristics
- The daemons handle relatively low traffic volumes (typically < 10 concurrent
  requests)

Simple threaded and selector-based implementations provide better code clarity,
easier maintenance, and are sufficient for Ganeti's cluster management workload.


Proposed changes
----------------

To remove the dependency on the deprecated asyncore module and reduce code
complexity, we propose migrating to simpler, more maintainable implementations
using standard library components:

- Threaded HTTP server
- Selector-based daemon event loop using the ``selectors`` module
- Threaded inotify file watcher
- Migration strategy for remaining asyncore components

The migration will be performed incrementally to minimize risk and allow
thorough testing at each stage. The ultimate goal is to ship version 3.2
without any dependency on asyncore.


Simple Threaded HTTP Server
+++++++++++++++++++++++++++

The implementation will replace the asyncore-based HTTP server with Python's
standard ``http.server`` module using a ``ThreadPoolExecutor`` for concurrent
request handling.

Neither the node daemon nor the RAPI daemon experience heavy traffic. A threaded
HTTP server will be more than sufficient for Ganeti's workload characteristics.
Each request will be handled in a separate thread from a thread pool, providing:

- Simpler code
- Better performance
- Reduced memory usage per request
- Full backward compatibility with existing handler implementations

The upcoming improvements to Python's GIL in Python 3.13+ will further enhance
performance, though the new implementation should meet all performance
requirements.


Daemon Event Loop
+++++++++++++++++

The current ``Mainloop`` class in lib/daemon.py uses ``asyncore.loop()`` to
monitor file descriptors for I/O readiness. Once the HTTP server runs
independently in threads, the event loop will only monitor two components:

1. **AsyncAwaker**: A socketpair used to wake the event loop from signal
   handlers (SIGTERM, SIGINT, SIGCHLD)
2. **AsyncNotifier**: The inotify file descriptor for watching configuration
   files (RAPI users file)

The ``asyncore.loop()`` implementation uses ``poll()`` or ``select()`` under
the hood to wait for I/O events on these file descriptors. We propose replacing
this with Python's ``selectors`` module, which provides a high-level interface
to the same underlying system calls.

Signal handling considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current signal handling mechanism uses ``AsyncAwaker`` to safely communicate
between signal handlers and the main event loop. Signal handlers write a byte
to a socketpair, waking the event loop which then processes the signal in a
safe context.

This mechanism is POSIX-compliant and avoids common signal handling pitfalls
(async-signal-safety violations). The selector-based implementation preserves
this design pattern while removing the asyncore dependency.


Inotify File Watcher
+++++++++++++++++++++

The RAPI daemon uses ``AsyncNotifier`` (lib/asyncnotifier.py) to monitor
``/var/lib/ganeti/rapi/users`` for changes. When the file is modified, the
daemon automatically reloads user credentials without requiring a restart.

The current implementation inherits from ``asyncore.file_dispatcher`` to
integrate the inotify file descriptor with the asyncore event loop. This
requires coordination between the inotify events and the main event loop.

Since the HTTP server will be threaded and operate independently, using a
thread for file watching will be architecturally consistent and simpler. This
approach will eliminate the need for event loop coordination entirely. The
watcher will run in a daemon thread, checking for inotify events with a timeout.
When events occur, the callback will be invoked directly.

Benefits of the threaded approach:

- Simpler implementation (no event loop coordination)
- Architecturally consistent with threaded HTTP server
- Easier to test in isolation

Trade-offs:

- Additional thread
- Callback runs in watcher thread (must be thread-safe)
- 1-second maximum latency for file change detection (acceptable for user file
  updates)


UDP Client Socket (ConfdClient)
++++++++++++++++++++++++++++++++

The ``AsyncUDPSocket`` class in lib/daemon.py provides a base class for UDP
socket handling. Its only usage in Python code is by ``ConfdAsyncUDPClient`` in
lib/confd/client.py, which is a **client library** for querying the
configuration daemon (written in Haskell) - used within the Ganeti Watcher.

We propose to replace ``AsyncUDPSocket`` with a selector-compatible implementation.
Since the Watcher doesn't use ``Mainloop`` there is no direct dependency to
the other migration tasks.


Visible Changes
---------------

The migration is designed to be transparent to users and administrators. The
following aspects will remain unchanged:

Daemon invocation
+++++++++++++++++

No changes to command-line parameters, configuration files, or startup
procedures. All existing scripts and documentation remain valid.

HTTP API compatibility
++++++++++++++++++++++

The RAPI and node daemon HTTP APIs remain fully compatible:

- All endpoints continue to work identically
- Request/response formats unchanged
- Authentication and authorization mechanisms preserved
- TLS/SSL configuration continues to work
- Client code requires no modifications

Configuration files
+++++++++++++++++++

All existing configuration files continue to work without modification:

- RAPI users file (``/var/lib/ganeti/rapi/users``) format unchanged
- SSL certificate configuration unchanged
- No new configuration options required

Signal handling
+++++++++++++++

Daemon signal handling remains unchanged:

- SIGTERM/SIGINT trigger graceful shutdown
- SIGHUP triggers log file rotation
- SIGCHLD handling for child processes (if applicable)

Testing requirements
++++++++++++++++++++

The lack of visible changes significantly reduces testing requirements:

- Existing QA tests should pass without modification
- RAPI client libraries continue to work
- Cluster upgrades proceed normally
- No documentation updates required for users

This approach minimizes risk and allows the migration to proceed incrementally
with confidence that regressions will be easily detected.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
