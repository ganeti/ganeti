===================
Multi-version tests
===================

.. contents:: :depth: 4

This is a design document describing how tests which use multiple
versions of Ganeti can be introduced into the current build
infrastructure.

Desired improvements
====================

The testing of Ganeti is currently done by using two different
approaches - unit tests and QA. While the former are useful for ensuring
that the individual parts of the system work as expected, most errors
are discovered only when all the components of Ganeti interact during
QA.

However useful otherwise, until now the QA has failed to provide support
for testing upgrades and version compatibility as it was limited to
using only one version of Ganeti. While these can be tested for every
release manually, a systematic approach is preferred and none can exist
with this restriction in place. To lift it, the buildbot scripts and QA
utilities must be extended to allow a way of specifying and using
diverse multi-version checks.

Required use cases
==================

There are two classes of multi-version tests that are interesting in
Ganeti, and this chapter provides an example from each to highlight what
should be accounted for in the design.

Compatibility tests
-------------------

One interface Ganeti exposes to clients interested in interacting with
it is the RAPI. Its stability has always been a design principle
followed during implementation, but whether it held true in practice was
not asserted through tests.

An automatic test of RAPI compatibility would have to take a diverse set
of RAPI requests and perform them on two clusters of different versions,
one of which would be the reference version. If the clusters had been
identically configured, all of the commands successfully executed on the
reference version should succeed on the newer version as well.

To achieve this, two versions of Ganeti can be run separately on a
cleanly setup cluster. With no guarantee that the versions can coexist,
the deployment of these has to be separate. A proxy placed between the
client and Ganeti records all the requests and responses. Using this
data, a testing utility can decide if the newer version is compatible or
not, and provide additional information to assist with debugging.

Upgrade / downgrade tests
-------------------------

An upgrade / downgrade test serves to examine whether the state of the
cluster is unchanged after its configuration has been upgraded or
downgraded to another version of Ganeti.

The test works with two consecutive versions of Ganeti, both installed
on the same machine. It examines whether the configuration data and
instances survive the downgrade and upgrade procedures. This is done by
creating a cluster with the newer version, downgrading it to the older
one, and upgrading it to the newer one again. After every step, the
integrity of the cluster is checked by running various operations and
ensuring everything still works.

Design and implementation
=========================

Although the previous examples have not been selected to show use cases
as diverse as possible, they still show a number of dissimilarities:

- Parallel installation vs sequential deployments
- Comparing with reference version vs comparing consecutive versions
- Examining result dumps vs trying a sequence of operations

With the first two real use cases demonstrating such diversity, it does
not make sense to design multi-version test classes. Instead, the
programmability of buildbot's configuration files can be leveraged to
implement each test as a separate builder with a custom sequence of
steps. The individual steps such as checking out a given or previous
version, or installing and removing Ganeti, will be provided as utility
functions for any test writer to use.

Current state
-------------

An upgrade / downgrade test is a part of the QA suite as of commit
aa104b5e. The test and the corresponding buildbot changes are a very
good first step, both by showing that multi-version tests can be done,
and by providing utilities needed for builds of multiple branches.
Previously, the same folder was used as the base directory of any build,
and now a directory structure more accommodating to multiple builds is
in place.

The builder running the test has one flaw - regardless of the branch
submitted, it compares versions 2.10 and 2.11 (current master). This
behaviour is different from any of the other builders, which may
restrict the branches a test can be performed on, but do not
differentiate between them otherwise. While additional builders for
different versions pairs may be added, this is not a good long-term
solution.

The test can be improved by making it compare the current and the
previous version. As the buildbot has no notion of what a previous
version is, additional utilities to handle this logic will have to be
introduced.

Planned changes
---------------

The upgrade / downgrade test should be generalized to work for any
version which can be downgraded from and upgraded to automatically,
meaning versions from 2.11 onwards. This will be made challenging by
the fact that the previous version has to be checked out by reading the
version of the currently checked out code, identifying the previous
version, and then making yet another checkout.

The major and minor version can be read from a Ganeti repository in
multiple ways. The two are present as constants defined in source files,
but due to refactorings shifting constants from the Python to the
Haskell side, their position varies across versions. A more reliable way
of fetching them is by examining the news file, as it obeys strict
formatting restrictions.

With the version found, a script that acts as a previous version
lookup table can be invoked. This script can be constructed dynamically
upon buildbot startup, and specified as a build step. The checkout
following it proceeds as expected.

The RAPI compatibility test should be added as a separate builder
afterwards. As the test requires additional comparison and proxy logic
to be used, it will be enabled only on 2.11 onwards, comparing the
versions to 2.6 - the reference version for the RAPI. Details on the
design of this test will be added in a separate document.

Potential issues
================

While there are many advantages to having a single builder representing
a multi-version test, working on every branch, there is at least one
disadvantage: the need to define a base or reference version, which is
the only version that can be used to trigger the test, and the only one
on which code changes can be tried.

If an error is detected while running a test, and the issue lies with
a version other than the one used to invoke the test, the fix would
have to make it into the repository before the test could be tried
again.

For simple tests, the issue might be mitigated by running them locally.
However, the multi-version tests are more likely to be complicated than
not, and it could be difficult to reproduce a test by hand.

The situation can be made simpler by requiring that any multi-version
test can use only versions lower than the reference version. As errors
are more likely to be found in new rather than old code, this would at
least reduce the number of troublesome cases.
