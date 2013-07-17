=====================================
Unit tests for cmdlib / LogicalUnit's
=====================================

.. contents:: :depth: 4

This is a design document describing unit tests for the cmdlib module.
Other modules are deliberately omitted, as LU's contain the most complex
logic and are only sparingly tested.

Current state and shortcomings
==============================

The current test coverage of the cmdlib module is at only ~14%. Given
the complexity of the code this is clearly too little.

The reasons for this low coverage are numerous. There are organisational
reasons, like no strict requirements for unit tests for each feature.
But there are also design and technical reasons, which this design
document wants to address. First, it's not clear which parts of LU's
should be tested by unit tests, i.e. the test boundaries are not clearly
defined. And secondly, it's too hard to actually write unit tests for
LU's. There exists no good framework or set of tools to write easy to
understand and concise tests.

Proposed changes
================

This design document consists of two parts. Initially, the test
boundaries for cmdlib are laid out, and considerations about writing
unit tests are given. Then the test framework is described, together
with a rough overview of the individual parts and how they are meant
to be used.

Test boundaries
---------------

For the cmdlib module, every LogicalUnit is seen as a unit for testing.
Unit tests for LU's may only execute the LU but make sure that no side
effect (like filesystem access, network access or the like) takes
place. Smaller test units (like individual methods) are sensible and
will be supported by the test framework. However, they are not the main
scope of this document.

LU's require the following environment to be provided by the test code
in order to be executed:

An input opcode
  LU's get all the user provided input and parameters from the opcode.
The command processor
  Used to get the execution context id and to output logging  messages.
  It also drives the execution of LU's by calling the appropriate
  methods in the right order.
The Ganeti context
  Provides node-management methods and contains

   * The configuration. This gives access to the cluster configuration.
   * The Ganeti Lock Manager. Manages locks during the execution.

The RPC runner
  Used to communicate with node daemons on other nodes and to perform
  operations on them.

The IAllocator runner
  Calls the IAllocator with a given request.

All of those components have to be replaced/adapted by the test
framework.

The goal of unit tests at the LU level is to exercise every possible
code path in the LU at least once. Shared methods which are used by
multiple LU's should be made testable by themselves and explicit unit
tests should be written for them.

Ultimately, the code coverage for the cmdlib module should be higher
than 90%. As Python is a dynamic language, a portion of those tests
only exists to exercise the code without actually asserting for
anything in the test. They merely make sure that no type errors exist
and that potential typos etc. are caught at unit test time.

Test framework
--------------

The test framework will it make possible to write short and concise
tests for LU's. In the simplest case, only an opcode has to be provided
by the test. The framework will then use default values, like an almost
empty configuration with only the master node and no instances.

All aspects of the test environment will be configurable by individual
tests.

MCPU mocking
************

The MCPU drives the execution of LU's. It has to perform its usual
sequence of actions, but additionally it has to provide easy access to
the log output of LU's. It will contain utility assertion methods on the
output.

The mock will be a sub-class of ``mcpu.Processor`` which overrides
portions of it in order to support the additional functionality. The
advantage of being a sub-class of the original processor is the
automatic compatibility with the code running in real clusters.

Configuration mocking
*********************

Per default, the mocked configuration will contain only the master node,
no instances and default parameters. However, convenience methods for
the following use cases will be provided:

 - "Shortcut" methods to add objects to the configuration.
 - Helper methods to quickly create standard nodes/instances/etc.
 - Pre-populated default configurations for standard use-cases (i.e.
   cluster with three nodes, five instances, etc.).
 - Convenience assertion methods for checking the configuration.

Lock mocking
************

Initially, the mocked lock manager always grants all locks. It performs
the following tasks:

 - It keeps track of requested/released locks.
 - Provides utility assertion methods for checking locks (current and
   already released ones).

In the future, this component might be extended to prevent locks from
being granted. This could eventually be used to test optimistic locking.

RPC mocking
***********

No actual RPC can be made during unit tests. Therefore, those calls have
to be replaced and their results mocked. As this will entail a large
portion of work when writing tests, mocking RPC's will be made as easy as
possible. This entails:

 - Easy construction of RPC results.
 - Easy mocking of RPC calls (also multiple ones of the same type during
   one LU execution).
 - Asserting for RPC calls (including arguments, affected nodes, etc.).

IAllocator mocking
******************

Calls (also multiple ones during the execution of a LU) to the
IAllocator interface have to be mocked. The framework will provide,
similarly to the RPC mocking, provide means to specify the mocked result
and to assert on the IAllocator requests.

Future work
===========

With unit tests for cmdlib in place, further unit testing for other
modules can and should be added. The test boundaries therefore should be
aligned with the boundaries from cmdlib.

The mocked locking module can be extended to allow testing of optimistic
locking in LU's. In this case, on all requested locks are actually
granted to the LU, so it has to adapt for this situation correctly.

A higher test coverage for LU's will increase confidence in our code and
tests. Refactorings will be easier to make as more problems are caught
during tests.

After a baseline of unit tests is established for cmdlib, efficient
testing guidelines could be put in place. For example, new code could be
required to not lower the test coverage in cmdlib. Additionally, every
bug fix could be required to include a test which triggered the bug
before the fix is created.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
