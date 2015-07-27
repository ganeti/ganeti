.. Ganeti documentation master file,
   created by sphinx-quickstart

Welcome to Ganeti's documentation!
==================================

This page is the starting point for browsing the Ganeti
documentation. Below, the corpus of Ganeti documentation is grouped by
topic.

A few quick references:

- :doc:`glossary`: Provides explanations of basic Ganeti terminology.
- :doc:`news` file: Lists changes between Ganeti versions.
- :ref:`search`: Allows you to search for key terms across Ganeti documentation.

Installing Ganeti
+++++++++++++++++

Use the following resources to install and/or upgrade Ganeti:

- :doc:`install`: Comprehensive instructions for installing Ganeti.
- :doc:`install-quick`: A shortened installation guide for the experienced Ganeti user.
- :doc:`upgrade`: Instructions for upgrading an existing Ganeti installation to the latest version.

Using Ganeti
++++++++++++

The following resources provide guidance on how to use Ganeti:

- :doc:`admin`: Information about how to manage a Ganeti cluster after it is installed (including management of nodes and instances, and information about Ganeti's tools and monitoring agent).
- :doc:`walkthrough`: An example-oriented guide to Ganeti.
- :doc:`manpages`: Descriptions of the various tools that are part of Ganeti.
- :doc:`security`: A description of the security model underlying a Ganeti cluster.
- :doc:`hooks`: Information on hooking scripts, which extend Ganeti functionalities by automatically activating when certain events occur.
- :doc:`iallocator`: Description of the API for external tools, which can allocate instances either manually or automatically.
- :doc:`rapi`: Description of the Ganeti remote API, which allows programmatic access to most of the functionalities of Ganeti.
- :doc:`ovfconverter`: Description of a tool that provides compatibility with the standard OVF virtual machine interchange format.
- :doc:`virtual-cluster`: Explanation of how to use virtual cluster support, which is utilized mainly for testing reasons.

Some features are explicitly targeted for large Ganeti installations,
in which multiple clusters are present:

- :doc:`cluster-merge`: Describes a tool for merging two existing clusters.
- :doc:`move-instance`: Describes how to move instances between clusters.

Developing Ganeti
+++++++++++++++++

There are a few documents particularly useful for developers who want
to modify Ganeti:

- :doc:`locking`: Describes Ganeti's locking strategy and lock order dependencies.
- :doc:`devnotes`: Details build dependencies and other useful development-related information.


Implemented designs
-------------------

Before actual implementation, all Ganeti features are described in a
design document. Designs fall into two categories: released versions
and draft versions (which are either incomplete or not implemented).

.. toctree::
   :maxdepth: 1

   design-2.0.rst
   design-2.1.rst
   design-2.2.rst
   design-2.3.rst
   design-htools-2.3.rst
   design-2.4.rst
   design-2.5.rst
   design-2.6.rst
   design-2.7.rst
   design-2.8.rst
   design-2.9.rst
   design-2.10.rst
   design-2.11.rst
   design-2.12.rst
   design-2.13.rst
   design-2.14.rst
   design-2.15.rst
   design-2.16.rst

Draft designs
-------------
.. toctree::
   :maxdepth: 2

   design-draft.rst

.. toctree::
   :hidden:

   admin.rst
   cluster-merge.rst
   cluster-keys-replacement.rst
   design-allocation-efficiency.rst
   design-autorepair.rst
   design-bulk-create.rst
   design-chained-jobs.rst
   design-cmdlib-unittests.rst
   design-cpu-speed.rst
   design-cpu-pinning.rst
   design-dedicated-allocation.rst
   design-device-uuid-name.rst
   design-daemons.rst
   design-disk-conversion.rst
   design-disks.rst
   design-file-based-storage.rst
   design-file-based-disks-ownership.rst
   design-hroller.rst
   design-hsqueeze.rst
   design-hotplug.rst
   design-internal-shutdown.rst
   design-kvmd.rst
   design-location.rst
   design-linuxha.rst
   design-lu-generated-jobs.rst
   design-monitoring-agent.rst
   design-move-instance-improvements.rst
   design-multi-reloc.rst
   design-multi-version-tests.rst
   design-network.rst
   design-node-add.rst
   design-node-security.rst
   design-oob.rst
   design-openvswitch.rst
   design-opportunistic-locking.rst
   design-optables.rst
   design-os.rst
   design-ovf-support.rst
   design-partitioned
   design-performance-tests.rst
   design-plain-redundancy.rst
   design-query2.rst
   design-query-splitting.rst
   design-reason-trail.rst
   design-restricted-commands.rst
   design-shared-storage.rst
   design-shared-storage-redundancy.rst
   design-ssh-ports.rst
   design-storagetypes.rst
   design-systemd.rst
   design-upgrade.rst
   design-virtual-clusters.rst
   devnotes.rst
   dev-codestyle.rst
   glossary.rst
   hooks.rst
   iallocator.rst
   install.rst
   install-quick.rst
   locking.rst
   manpages.rst
   monitoring-query-format.rst
   move-instance.rst
   news.rst
   ovfconverter.rst
   rapi.rst
   security.rst
   upgrade.rst
   virtual-cluster.rst
   walkthrough

.. vim: set textwidth=72 :
